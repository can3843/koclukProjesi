"""Estimated net range per test and session (CLAUDE.md §6.6). Always a range, never a promise."""

from . import config
from .needs import current_rate, exam_day_rate
from .types import ProjectionResult, SessionProjection, TestProjection, TopicState


def _completed_ids(inp, sequence, needs_by_id):
    """Included topics counted as finished by exam day, shortened when the student's pace is below 1."""
    if inp.pace is None or inp.pace >= 1 or inp.plan_age_days < config.PACE_MIN_PLAN_AGE_DAYS:
        return set(sequence)
    total = sum(needs_by_id[t].need for t in sequence)
    allowed = total * max(0.0, inp.pace)
    done, used = set(), 0.0
    for tid in sequence:
        if used + needs_by_id[tid].need > allowed:
            break
        done.add(tid)
        used += needs_by_id[tid].need
    return done


def _calibration(inp, subject_id, now_estimate):
    """Ratio of the student's latest mock nets to our current estimate, kept inside safe bounds."""
    nets = [m.nets[subject_id] for m in inp.mocks if subject_id in m.nets][: config.CALIBRATION_MOCK_COUNT]
    if not nets or now_estimate <= 0:
        return 1.0
    low, high = config.MOCK_CALIBRATION_BOUNDS
    return min(high, max(low, (sum(nets) / len(nets)) / now_estimate))


def project(inp, sequence, needs_by_id):
    subject_test = {s.id: s.test_slug for s in inp.subjects}
    completed = _completed_ids(inp, sequence, needs_by_id)

    now_by_subject, exam_by_subject = {}, {}
    for topic in inp.topics:
        state = inp.states.get(topic.id) or TopicState()
        if state.state == "learned":
            now = exam = exam_day_rate(state)
        else:
            now = current_rate(state)
            exam = exam_day_rate(state) if topic.id in completed else now
        sid = topic.subject_id
        now_by_subject[sid] = now_by_subject.get(sid, 0.0) + topic.avg_questions * now
        exam_by_subject[sid] = exam_by_subject.get(sid, 0.0) + topic.avg_questions * exam

    test_now, test_exam = {}, {}
    for sid, now in now_by_subject.items():
        slug = subject_test[sid]
        factor = _calibration(inp, sid, now)
        test_now[slug] = test_now.get(slug, 0.0) + now
        test_exam[slug] = test_exam.get(slug, 0.0) + exam_by_subject[sid] * factor

    def to_range(exam_value, cap):
        low = round(exam_value * config.PROJECTION_LOW)
        high = min(round(exam_value * config.PROJECTION_HIGH), cap)
        return min(low, high), high

    tests, session_now, session_exam, session_cap = [], {}, {}, {}
    for test in inp.tests:
        now, exam = test_now.get(test.slug, 0.0), test_exam.get(test.slug, 0.0)
        low, high = to_range(exam, test.question_count)
        tests.append(TestProjection(test.slug, test.name, test.session_code, test.question_count, round(now), low, high))
        session_now[test.session_code] = session_now.get(test.session_code, 0.0) + now
        session_exam[test.session_code] = session_exam.get(test.session_code, 0.0) + exam
        session_cap[test.session_code] = session_cap.get(test.session_code, 0) + test.question_count

    sessions = []
    for code in inp.session_codes or tuple(session_cap):
        if code not in session_cap:
            continue
        low, high = to_range(session_exam[code], session_cap[code])
        sessions.append(SessionProjection(code, session_cap[code], round(session_now[code]), low, high))

    return ProjectionResult(tests=tuple(tests), sessions=tuple(sessions))
