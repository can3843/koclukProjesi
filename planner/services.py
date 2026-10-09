"""Bridge between the database and the pure plan engine (CLAUDE.md §6.1). Single entry points for views."""

from dataclasses import asdict

from django.db import transaction
from django.utils import timezone

from catalog.models import ExamSession, ExamTest, Subject, Topic

from .engine import make_plan
from .engine.types import MockResult, PlanInput, SessionInfo, SubjectInfo, TestInfo, TopicInfo, TopicState
from .models import MockExam, Plan, PlanTopic, TopicProgress


def track_topics(track):
    """Active topics of the student's track, in curriculum order."""
    return (
        Topic.objects.filter(is_active=True, subject__test__tracks=track)
        .select_related("subject__test__session")
        .prefetch_related("prerequisites")
        .order_by("subject__test__session__order", "subject__test__order", "subject__order", "order")
    )


def ensure_progress_rows(user, track):
    """Create the default (level 0) progress row for every topic of the track that has none yet."""
    existing = set(TopicProgress.objects.filter(user=user).values_list("topic_id", flat=True))
    missing = [
        TopicProgress(user=user, topic=topic)
        for topic in track_topics(track)
        if topic.pk not in existing
    ]
    TopicProgress.objects.bulk_create(missing)
    return len(missing)


def first_session(exam):
    return ExamSession.objects.filter(exam=exam).order_by("order").first()


def exam_countdown(profile, today=None):
    """Days left until exam day and whether the date is an estimate; None if unknown."""
    if profile is None or profile.exam_id is None:
        return None
    session = first_session(profile.exam)
    if session is None:
        return None
    today = today or timezone.localdate()
    return {
        "days": max(0, (session.date - today).days),
        "estimated": session.date_is_estimated,
        "date": session.date,
        "code": session.code,
    }


def build_engine_input(user, today, extra_minutes_per_day=0):
    profile = user.student_profile
    track = profile.track
    tests = list(ExamTest.objects.filter(tracks=track).select_related("session").order_by("session__order", "order"))
    subjects = list(Subject.objects.filter(test__in=tests).order_by("test__session__order", "test__order", "order"))
    topics = list(track_topics(track))

    sessions = list(ExamSession.objects.filter(exam=profile.exam).order_by("order"))
    track_codes = []
    for test in tests:
        if test.session.code not in track_codes:
            track_codes.append(test.session.code)

    states = {}
    for row in TopicProgress.objects.filter(user=user, topic__in=topics):
        states[row.topic_id] = TopicState(
            level=row.level,
            state=row.state,
            remaining_learn=row.remaining_learn_minutes,
            remaining_practice=row.remaining_practice_minutes,
            boost=row.boost,
            solved=row.questions_solved,
            correct=row.questions_correct,
            wrong=row.questions_wrong,
            override=row.user_override,
        )

    mocks = []
    for mock in MockExam.objects.filter(user=user).prefetch_related("scores")[:10]:
        mocks.append(MockResult(nets={s.subject_id: float(s.net) for s in mock.scores.all()}))

    return PlanInput(
        today=today,
        sessions=tuple(SessionInfo(s.code, s.date, s.duration_minutes) for s in sessions),
        session_codes=tuple(track_codes),
        tests=tuple(TestInfo(t.slug, t.name, t.session.code, t.question_count) for t in tests),
        subjects=tuple(SubjectInfo(s.id, s.name, s.test.slug, s.order, s.question_count) for s in subjects),
        topics=tuple(
            TopicInfo(
                id=t.pk,
                subject_id=t.subject_id,
                subject_order=t.subject.order,
                order=t.order,
                name=t.name,
                avg_questions=float(t.avg_questions),
                learn_hours=float(t.learn_hours),
                difficulty=t.difficulty,
                prerequisites=tuple(sorted(p.pk for p in t.prerequisites.all())),
            )
            for t in topics
        ),
        states=states,
        weekday_minutes=profile.weekday_minutes,
        weekend_minutes=profile.weekend_minutes,
        rest_weekday=profile.rest_weekday,
        mocks=tuple(mocks),
        extra_minutes_per_day=extra_minutes_per_day,
    )


def _projection_json(projection):
    return {
        "tests": [asdict(t) for t in projection.tests],
        "sessions": [asdict(s) for s in projection.sessions],
    }


@transaction.atomic
def build_plan(user, today=None, reason=Plan.Reason.MANUAL):
    """Create a new active plan for the user (and deactivate the previous one)."""
    today = today or timezone.localdate()
    profile = user.student_profile
    ensure_progress_rows(user, profile.track)

    result = make_plan(build_engine_input(user, today))

    Plan.objects.filter(user=user, is_active=True).update(is_active=False)
    budget = asdict(result.budget)
    budget.update(
        fits_all=result.fits_all,
        mock_count=result.mock_count,
        exam_date=result.exam_date.isoformat(),
    )
    projection = _projection_json(result.projection)
    if result.plus_hour_projection is not None:
        projection["plus_hour"] = _projection_json(result.plus_hour_projection)

    plan = Plan.objects.create(
        user=user,
        reason=reason,
        phase_code=result.phase_code,
        days_left=result.days_left,
        budget=budget,
        required_minutes=result.required_minutes,
        coverage_ratio=result.coverage_ratio,
        projection=projection,
        is_active=True,
    )
    PlanTopic.objects.bulk_create(
        PlanTopic(
            plan=plan,
            topic_id=t.topic_id,
            included=t.included,
            sequence=t.sequence,
            priority=t.priority,
            gain=t.gain,
            need_minutes=t.need_minutes,
            reason_code=t.reason_code,
            start_day=t.start_day,
        )
        for t in result.topics
    )
    return plan


def get_active_plan(user):
    return Plan.objects.filter(user=user, is_active=True).first()
