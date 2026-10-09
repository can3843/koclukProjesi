"""Bridge between the database and the pure plan engine (CLAUDE.md §6.1). Single entry points for views."""

from collections import defaultdict
from dataclasses import asdict
from datetime import date as date_cls, timedelta

from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Greatest
from django.utils import timezone

from catalog.models import ExamSession, ExamTest, Subject, Topic

from .engine import config, make_plan
from .engine.adaptation import (
    compute_streak, decayed_boost, extra_practice_minutes, missed_task_ids, pace_of, propose_rescope, raised_boost,
    rescope_needed,
)
from .engine.capacity import build_days, sum_budget
from .engine.needs import build_need, candidate_needs
from .engine.phases import phase_for
from .engine.reviews import accuracy_of, after_review, first_review
from .engine.scheduler import ReviewDue, ScheduleTopic, schedule
from .engine.types import MockResult, PlanInput, SessionInfo, SubjectInfo, TestInfo, TopicInfo, TopicState
from .messages import weekly_message
from .models import (
    MockExam, MockScore, Plan, PlanTopic, ReviewItem, StudentProfile, Task, TopicProgress, WeeklyReview,
)


class TaskError(Exception):
    """A task action that cannot be done; `status` is the HTTP status the endpoint answers with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- catalog helpers

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


# ---------------------------------------------------------------- engine input

def compute_pace(user, today):
    """Done minutes / planned minutes of the last 14 days (today excluded); None without enough history."""
    start = today - timedelta(days=config.PACE_WINDOW_DAYS)
    rows = list(Task.objects.filter(user=user, date__gte=start, date__lt=today).values_list("date", "status", "minutes"))
    if len({day for day, _, _ in rows}) < config.PACE_MIN_PLANNED_DAYS:
        return None
    planned = sum(minutes for _, _, minutes in rows)
    done = sum(minutes for _, status, minutes in rows if status == Task.Status.DONE)
    return pace_of(done, planned)


def plan_age_days(user, today):
    """Days since the student's first plan was made (the pace correction starts after two weeks)."""
    first = Plan.objects.filter(user=user).order_by("created_at").first()
    if first is None:
        return 0
    return max(0, (today - timezone.localtime(first.created_at).date()).days)


def known_mock_dates(user):
    """Days of mocks that were taken, missed or are still planned (keeps the mock calendar stable)."""
    dates = set(Task.objects.filter(user=user, kind=Task.Kind.MOCK).values_list("date", flat=True))
    dates |= set(MockExam.objects.filter(user=user).values_list("taken_on", flat=True))
    return tuple(sorted(dates))


def build_engine_input(user, today, extra_minutes_per_day=0):
    profile = user.student_profile
    track = profile.track
    tests = list(ExamTest.objects.filter(tracks=track).select_related("session").order_by("session__order", "order"))
    subjects = list(Subject.objects.filter(test__in=tests).select_related("test").order_by("test__session__order", "test__order", "order"))
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
        known_mock_dates=known_mock_dates(user),
        pace=compute_pace(user, today),
        plan_age_days=plan_age_days(user, today),
    )


def _projection_json(projection):
    return {
        "tests": [asdict(t) for t in projection.tests],
        "sessions": [asdict(s) for s in projection.sessions],
    }


# ---------------------------------------------------------------- plan

def clear_future_tasks(user, today):
    """Delete pending tasks from today on. Today stays untouched once something was done today."""
    pending = Task.objects.filter(user=user, status=Task.Status.PENDING)
    if Task.objects.filter(user=user, date=today, status=Task.Status.DONE).exists():
        pending = pending.filter(date__gt=today)
    else:
        pending = pending.filter(date__gte=today)
    return pending.delete()[0]


@transaction.atomic
def build_plan(user, today=None, reason=Plan.Reason.MANUAL):
    """Create a new active plan (and its next 7 days of tasks); the previous plan is deactivated."""
    today = today or timezone.localdate()
    profile = user.student_profile
    ensure_progress_rows(user, profile.track)
    clear_future_tasks(user, today)

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
    generate_tasks(user, plan, today)
    return plan


def get_active_plan(user):
    return Plan.objects.filter(user=user, is_active=True).first()


# ---------------------------------------------------------------- task generation

def _schedule_topic(topic, need, progress):
    subject = topic.subject
    if need is not None:
        learn = need.learn_need if progress.remaining_learn_minutes is None else progress.remaining_learn_minutes
        practice = need.practice_need if progress.remaining_practice_minutes is None else progress.remaining_practice_minutes
    else:
        learn = practice = 0
    return ScheduleTopic(
        id=topic.pk,
        name=topic.name,
        subject_id=subject.pk,
        subject_name=subject.name,
        group=subject.group,
        difficulty=topic.difficulty,
        is_big=float(topic.learn_hours) > config.BIG_TOPIC_HOURS,
        minutes_per_question=float(subject.minutes_per_question),
        prerequisites=tuple(sorted(p.pk for p in topic.prerequisites.all())),
        learn_remaining=float(learn),
        practice_remaining=float(practice),
        started=progress.state == TopicProgress.State.IN_PROGRESS,
        level=progress.level,
    )


def generate_tasks(user, plan, today):
    """Create tasks for the days of the next week that have none yet (bulk, one pass)."""
    profile = user.student_profile
    exam_date = first_session(profile.exam).date
    window_end = min(today + timedelta(days=config.WINDOW_DAYS), exam_date)
    if window_end <= today:
        return []

    inp = build_engine_input(user, today)
    days = [d for d in build_days(inp) if d.date < window_end]

    existing = defaultdict(list)
    for task in Task.objects.filter(user=user, date__gte=today, date__lt=window_end):
        existing[task.date].append(task)
    committed = {
        day: [(t.topic_id, t.kind, t.minutes, t.review_item_id) for t in tasks if t.status == Task.Status.PENDING]
        for day, tasks in existing.items()
    }

    plan_topics = list(plan.plan_topics.filter(included=True).order_by("sequence"))
    sequence = [pt.topic_id for pt in plan_topics]
    needs = {n.topic.id: n for n in candidate_needs(inp)}
    topics = {t.pk: t for t in track_topics(profile.track)}
    progress = {p.topic_id: p for p in TopicProgress.objects.filter(user=user, topic_id__in=topics)}

    schedule_topics = {}
    for topic_id, topic in topics.items():
        include_needs = needs.get(topic_id) if topic_id in set(sequence) else None
        schedule_topics[topic_id] = _schedule_topic(topic, include_needs, progress[topic_id])

    # practice on topics outside the active scope: weak topics, recently learned ones, then level-2 topics
    sequence_set = set(sequence)
    pool = []
    for topic_id, row in progress.items():
        if topic_id in sequence_set or topic_id not in topics:
            continue
        if row.boost > 1.0:
            pool.append((0, -row.boost, topic_id))
        elif row.state == TopicProgress.State.LEARNED:
            pool.append((1, -(row.learned_on.toordinal() if row.learned_on else 0), topic_id))
        elif row.level == 2 and row.state != TopicProgress.State.EXCLUDED and row.user_override != "force_exclude":
            pool.append((2, topics[topic_id].subject.order * 1000 + topics[topic_id].order, topic_id))
    fallback_ids = [topic_id for *_, topic_id in sorted(pool)]

    reviews = [
        ReviewDue(item.pk, item.topic_id, item.due_date)
        for item in ReviewItem.objects.filter(user=user, is_active=True, due_date__lt=window_end)
        if item.topic_id in schedule_topics
    ]

    planned = schedule(days, schedule_topics, sequence, fallback_ids, reviews, committed)

    session_ids = {s.code: s.pk for s in ExamSession.objects.filter(exam=profile.exam)}
    subject_ids = {t.pk: t.subject_id for t in topics.values()}
    created = Task.objects.bulk_create(
        Task(
            user=user,
            plan=plan,
            date=item.date,
            kind=item.kind,
            topic_id=item.topic_id,
            subject_id=item.subject_id if item.subject_id is not None else subject_ids.get(item.topic_id),
            session_id=session_ids.get(item.session_code) if item.session_code else None,
            title=item.title,
            note=item.note,
            minutes=item.minutes,
            question_target=item.question_target,
            order=item.order,
            is_peak=item.is_peak,
            review_item_id=item.review_item_id,
        )
        for item in planned
    )
    return created


def regenerate_future(user, today):
    """Drop pending tasks after today and plan them again (after skips, learned topics, failed reviews)."""
    plan = get_active_plan(user)
    if plan is None:
        return []
    Task.objects.filter(user=user, status=Task.Status.PENDING, date__gt=today).delete()
    return generate_tasks(user, plan, today)


# ---------------------------------------------------------------- daily state (lazy)

def _monday(day):
    return day - timedelta(days=day.weekday())


def decay_boosts(user, last_sync, today):
    """Boosts fade by BOOST_DECAY_PER_WEEK for every week boundary crossed since the last visit."""
    if last_sync is None:
        return 0
    weeks = (_monday(today) - _monday(last_sync)).days // 7
    if weeks <= 0:
        return 0
    amount = config.BOOST_DECAY_PER_WEEK * weeks
    return TopicProgress.objects.filter(user=user, boost__gt=1.0).update(boost=Greatest(1.0, F("boost") - amount))


@transaction.atomic
def ensure_daily_state(user, today=None):
    """Lazy daily housekeeping, run when a student opens the app (§6.9). Returns notices for the UI."""
    today = today or timezone.localdate()
    profile = StudentProfile.objects.select_for_update(of=("self",)).select_related("exam", "track").get(user=user)
    notices = {"missed": 0, "phase_changed": None}
    if profile.last_daily_sync == today or profile.exam_id is None:
        return notices

    # 1. tasks of days that are over and still pending become missed (their minutes stay queued)
    stale = list(Task.objects.filter(user=user, status=Task.Status.PENDING, date__lt=today).values_list("id", "date", "status"))
    missed_ids = missed_task_ids(stale, today)
    if missed_ids:
        Task.objects.filter(pk__in=missed_ids).update(status=Task.Status.MISSED)
    notices["missed"] = len(missed_ids)

    # 2. weekly boost decay
    decay_boosts(user, profile.last_daily_sync, today)

    exam_date = first_session(profile.exam).date
    days_left = (exam_date - today).days
    if days_left > 0:
        plan = get_active_plan(user)
        if plan is None:
            plan = build_plan(user, today, Plan.Reason.MANUAL)
        elif plan.phase_code != phase_for(days_left).code:
            # 3. a new phase starts: the strategy changes, so the plan is rebuilt
            notices["phase_changed"] = phase_for(days_left).code
            plan = build_plan(user, today, Plan.Reason.PHASE_CHANGE)
        elif missed_ids:
            # lost work goes back to the queue: plan the window again (never piled onto today)
            clear_future_tasks(user, today)
        # 4. last week's review, when a new week has started
        create_weekly_review(user, today)
        # 5. fill the window: days without any task get tasks (done work today is never regenerated)
        generate_tasks(user, plan, today)
        # 6. is the student behind? prepare a scope suggestion (not applied) for them to decide on
        profile.rescope_proposal = _daily_rescope_proposal(user, today)

    profile.last_daily_sync = today
    profile.save(update_fields=["last_daily_sync", "rescope_proposal"])
    return notices


# ---------------------------------------------------------------- scope suggestion (§6.8)

def _included_unfinished(user, inp):
    """(ids of the active plan's included topics that still have work left in study order, needs by id)."""
    plan = get_active_plan(user)
    needs = {n.topic.id: n for n in candidate_needs(inp)}
    if plan is None:
        return [], needs
    ids = plan.plan_topics.filter(included=True).order_by("sequence").values_list("topic_id", flat=True)
    return [tid for tid in ids if tid in needs and not needs[tid].user_excluded], needs


def compute_rescope(user, today, pace=None):
    """Dry run, no writes: topics to suggest dropping because the real pace is lower than the plan assumes."""
    pace = compute_pace(user, today) if pace is None else pace
    if pace is None or pace >= 1:
        return []
    inp = build_engine_input(user, today)
    included, needs = _included_unfinished(user, inp)
    if not included:
        return []
    remaining_need = sum(needs[tid].need for tid in included)
    remaining_budget = sum_budget(build_days(inp)).study_total
    if not rescope_needed(remaining_need, remaining_budget, pace):
        return []
    return propose_rescope(inp, included, pace)


def _daily_rescope_proposal(user, today):
    pace = compute_pace(user, today)
    topic_ids = compute_rescope(user, today, pace)
    if not topic_ids:
        return {}
    return {"topic_ids": topic_ids, "pace": round(pace, 2), "date": today.isoformat()}


def active_rescope_ids(profile, today):
    """Topic ids of the pending scope suggestion (empty when there is none or it was snoozed)."""
    ids = (profile.rescope_proposal or {}).get("topic_ids") or []
    if not ids:
        return []
    if profile.rescope_snoozed_until and profile.rescope_snoozed_until > today:
        return []
    return ids


@transaction.atomic
def apply_rescope(user, today=None):
    """The student agreed: drop the suggested topics (marked as excluded) and rebuild the plan."""
    today = today or timezone.localdate()
    topic_ids = compute_rescope(user, today)
    if topic_ids:
        TopicProgress.objects.filter(user=user, topic_id__in=topic_ids).update(user_override=TopicProgress.Override.FORCE_EXCLUDE)
        build_plan(user, today, Plan.Reason.RESCOPE)
    StudentProfile.objects.filter(user=user).update(rescope_proposal={}, rescope_snoozed_until=None)
    return topic_ids


def snooze_rescope(user, today=None):
    today = today or timezone.localdate()
    StudentProfile.objects.filter(user=user).update(rescope_snoozed_until=today + timedelta(days=config.RESCOPE_SNOOZE_DAYS))


# ---------------------------------------------------------------- weekly review (§4.7)

def _answered(task):
    return (task.correct or 0) + (task.wrong or 0) + (task.blank or 0)


def _topic_accuracy(tasks):
    """topic id -> (answered, correct) over done tasks that have results."""
    out = {}
    for task in tasks:
        if task.status != Task.Status.DONE or not task.topic_id or task.correct is None:
            continue
        answered, correct = out.get(task.topic_id, (0, 0))
        out[task.topic_id] = (answered + _answered(task), correct + task.correct)
    return out


def _best_improvement(this_week, previous_week):
    """(topic name, percentage points) of the topic whose accuracy rose most, or None."""
    now, before = _topic_accuracy(this_week), _topic_accuracy(previous_week)
    best = None
    for topic_id, (answered, correct) in now.items():
        old_answered, old_correct = before.get(topic_id, (0, 0))
        if answered < config.IMPROVEMENT_MIN_ANSWERED or old_answered < config.IMPROVEMENT_MIN_ANSWERED:
            continue
        points = round(100 * correct / answered - 100 * old_correct / old_answered)
        if points >= 1 and (best is None or points > best[1]):
            best = (topic_id, points)
    if best is None:
        return None
    return Topic.objects.get(pk=best[0]).name, best[1]


def _mock_changes(user, week_start, week_end):
    """Total net of the latest mock of each session this week versus the one before it."""
    mocks = MockExam.objects.filter(user=user, taken_on__lt=week_end).select_related("session").prefetch_related("scores")
    by_session = defaultdict(list)
    for mock in mocks:
        by_session[mock.session.code].append(mock)

    def total(mock):
        return float(sum(score.net for score in mock.scores.all()))

    changes = []
    for code, items in by_session.items():
        items.sort(key=lambda m: (m.taken_on, m.pk))
        latest = items[-1]
        if latest.taken_on < week_start or len(items) < 2:
            continue
        before, after = total(items[-2]), total(latest)
        changes.append({"session": code, "before": round(before, 2), "after": round(after, 2), "change": round(after - before, 2)})
    return changes


def _focus_subjects(user):
    rows = (
        TopicProgress.objects.filter(user=user, boost__gt=1.0)
        .select_related("topic__subject").order_by("-boost", "topic__subject__order")
    )
    names = []
    for row in rows:
        name = row.topic.subject.name
        if name not in names:
            names.append(name)
        if len(names) == config.FOCUS_SUBJECT_COUNT:
            break
    return names


def create_weekly_review(user, today):
    """Create the review of the previous week (Monday to Sunday) once, if the student had tasks in it."""
    this_monday = _monday(today)
    week_start = this_monday - timedelta(days=7)
    if WeeklyReview.objects.filter(user=user, week_start=week_start).exists():
        return None
    tasks = list(Task.objects.filter(user=user, date__gte=week_start, date__lt=this_monday))
    if not tasks:
        return None
    previous = list(Task.objects.filter(user=user, date__gte=week_start - timedelta(days=7), date__lt=week_start))

    planned = sum(t.minutes for t in tasks)
    done = sum(t.minutes for t in tasks if t.status == Task.Status.DONE)
    percent = round(100 * done / planned) if planned else 0
    with_results = [t for t in tasks if t.status == Task.Status.DONE and t.correct is not None]
    answered = sum(_answered(t) for t in with_results)
    correct = sum(t.correct for t in with_results)
    last_day = this_monday - timedelta(days=1)
    rows = list(Task.objects.filter(user=user, date__lte=last_day, date__gte=last_day - timedelta(days=400)).values_list("date", "status"))
    rest = getattr(user.student_profile, "rest_weekday", None)
    streak = compute_streak({d for d, st in rows if st == Task.Status.DONE}, {d for d, _ in rows}, rest, last_day)
    improved = _best_improvement(tasks, previous)
    focus = _focus_subjects(user)

    stats = {
        "planned_minutes": planned, "done_minutes": done, "percent": percent,
        "task_count": len(tasks), "done_count": sum(1 for t in tasks if t.status == Task.Status.DONE),
        "focus_minutes": sum(t.focus_seconds for t in tasks) // 60,
        "answered": answered, "correct": correct,
        "accuracy": round(100 * correct / answered) if answered else None,
        "streak": streak, "mock_changes": _mock_changes(user, week_start, this_monday),
        "improved": {"topic": improved[0], "points": improved[1]} if improved else None,
        "focus": focus,
    }
    message = weekly_message(percent, week_start, user.pk, improved, focus)
    return WeeklyReview.objects.create(user=user, week_start=week_start, stats=stats, message=message)


def unseen_review(user):
    return WeeklyReview.objects.filter(user=user, seen_at__isnull=True).order_by("-week_start").first()


# ---------------------------------------------------------------- mocks (§4.6, §6.8)

@transaction.atomic
def record_mock(user, session, taken_on, scores, task_id=None, today=None):
    """Save a mock exam result. `scores` maps Subject -> (correct, wrong, blank).

    A planned mock task of the same session and day is linked (and marked done) automatically.
    """
    today = today or timezone.localdate()
    mock = MockExam.objects.create(user=user, session=session, taken_on=taken_on)
    MockScore.objects.bulk_create(
        MockScore(mock=mock, subject=subject, correct=c, wrong=w, blank=b) for subject, (c, w, b) in scores.items()
    )
    linked = set(MockExam.objects.filter(user=user, task__isnull=False).values_list("task_id", flat=True))
    candidates = Task.objects.filter(user=user, kind=Task.Kind.MOCK, session=session).exclude(pk__in=linked)
    task = candidates.filter(pk=task_id).first() if task_id else None
    if task is None:
        task = candidates.filter(date=taken_on).order_by("id").first()
    if task is not None:
        mock.task = task
        mock.save(update_fields=["task"])
        if task.status == Task.Status.PENDING and task.date <= today:
            complete_task(task, today=today)
    # the new result changes the estimate, so the plan is made again
    build_plan(user, today, Plan.Reason.MANUAL)
    return mock


def _schedule_review_for_tomorrow(user, topic, today, exam_date):
    due = today + timedelta(days=1)
    if due >= exam_date:
        return
    item = ReviewItem.objects.filter(user=user, topic=topic, is_active=True).first()
    if item is None:
        ReviewItem.objects.create(user=user, topic=topic, due_date=due, interval_index=0)
    elif item.due_date > due:
        item.due_date = due
        item.save(update_fields=["due_date"])


@transaction.atomic
def set_weak_topics(user, mock, topic_ids, today=None):
    """Mark the topics the student struggled with in a mock: they come back with more weight."""
    today = today or timezone.localdate()
    subject_ids = list(mock.scores.values_list("subject_id", flat=True))
    chosen = list(Topic.objects.filter(pk__in=topic_ids, subject_id__in=subject_ids, is_active=True))
    already = set(mock.weak_topics.values_list("pk", flat=True))
    mock.weak_topics.set(chosen)
    exam_date = first_session(user.student_profile.exam).date
    new_topics = [t for t in chosen if t.pk not in already]
    for topic in new_topics:
        row = TopicProgress.objects.select_for_update().get(user=user, topic=topic)
        row.boost = raised_boost(row.boost)
        row.save(update_fields=["boost"])
        if row.state == TopicProgress.State.LEARNED:
            _schedule_review_for_tomorrow(user, topic, today, exam_date)
    if new_topics:
        build_plan(user, today, Plan.Reason.MANUAL)
    return chosen


def plan_suggestions(user, mock):
    """Weak topics outside the plan that are small enough to add ("do you want them in the plan?")."""
    plan = get_active_plan(user)
    if plan is None:
        return []
    in_plan = set(plan.plan_topics.filter(included=True).values_list("topic_id", flat=True))
    out = []
    for topic in mock.weak_topics.select_related("subject"):
        row = TopicProgress.objects.filter(user=user, topic=topic).first()
        if row is None or topic.pk in in_plan or row.user_override == TopicProgress.Override.FORCE_INCLUDE:
            continue
        if row.state == TopicProgress.State.LEARNED:
            continue
        if row.state == TopicProgress.State.EXCLUDED or float(topic.learn_hours) <= config.BIG_TOPIC_HOURS:
            out.append(topic)
    return out


@transaction.atomic
def add_topic_to_plan(user, topic, today=None):
    today = today or timezone.localdate()
    row = TopicProgress.objects.select_for_update().get(user=user, topic=topic)
    row.user_override = TopicProgress.Override.FORCE_INCLUDE
    if row.state == TopicProgress.State.EXCLUDED:
        row.state = TopicProgress.State.NOT_STARTED
    row.save()
    return build_plan(user, today, Plan.Reason.MANUAL)


# ---------------------------------------------------------------- settings (Phase 6)

@transaction.atomic
def update_schedule(user, weekday_minutes, weekend_minutes, rest_weekday, peak_time, today=None):
    """Save time budget, rest day and peak time. The plan is rebuilt only when the capacity changed."""
    today = today or timezone.localdate()
    profile = StudentProfile.objects.select_for_update().get(user=user)
    capacity_changed = (profile.weekday_minutes, profile.weekend_minutes, profile.rest_weekday) != (
        weekday_minutes, weekend_minutes, rest_weekday)
    profile.weekday_minutes = weekday_minutes
    profile.weekend_minutes = weekend_minutes
    profile.rest_weekday = rest_weekday
    profile.peak_time = peak_time
    profile.save(update_fields=["weekday_minutes", "weekend_minutes", "rest_weekday", "peak_time"])
    user.student_profile = profile  # build_plan reads the profile through the user
    if capacity_changed:
        build_plan(user, today, Plan.Reason.SETTINGS_CHANGE)
    return capacity_changed


@transaction.atomic
def change_track(user, track, today=None):
    """Switch to another track of the same exam: progress on shared topics is kept, the plan is made again."""
    today = today or timezone.localdate()
    profile = StudentProfile.objects.select_for_update().get(user=user)
    if track.exam_id != profile.exam_id:
        raise ValueError("Track belongs to another exam.")
    if profile.track_id == track.pk:
        return False
    profile.track = track
    profile.rescope_proposal = {}
    profile.rescope_snoozed_until = None
    profile.save(update_fields=["track", "rescope_proposal", "rescope_snoozed_until"])
    user.student_profile = profile  # build_plan reads the profile through the user
    ensure_progress_rows(user, track)
    build_plan(user, today, Plan.Reason.SETTINGS_CHANGE)
    return True


@transaction.atomic
def update_levels(user, levels, today=None):
    """Change topic levels. `levels` maps topic id -> 0/1/2; learned topics keep their state and are skipped.

    Returns the number of topics that changed; the plan is rebuilt when there is any.
    """
    today = today or timezone.localdate()
    rows = TopicProgress.objects.select_for_update().filter(user=user, topic_id__in=list(levels))
    changed = []
    for row in rows:
        new_level = levels[row.topic_id]
        if row.state == TopicProgress.State.LEARNED or row.level == new_level:
            continue
        row.level = new_level
        changed.append(row)
    TopicProgress.objects.bulk_update(changed, ["level"])
    if changed:
        build_plan(user, today, Plan.Reason.LEVELS_CHANGED)
    return len(changed)


@transaction.atomic
def set_topic_override(user, topic, override, today=None):
    """"Add anyway" (force_include), "take out" (force_exclude) or back to automatic (None) for one topic."""
    today = today or timezone.localdate()
    row = TopicProgress.objects.select_for_update().get(user=user, topic=topic)
    if row.state == TopicProgress.State.LEARNED or row.user_override == override:
        return False
    row.user_override = override
    if override == TopicProgress.Override.FORCE_INCLUDE and row.state == TopicProgress.State.EXCLUDED:
        row.state = TopicProgress.State.NOT_STARTED
    row.save(update_fields=["user_override", "state"])
    build_plan(user, today, Plan.Reason.SETTINGS_CHANGE)
    return True


def delete_account(user):
    """Remove the user and, through cascades, every piece of their data."""
    user.delete()


# ---------------------------------------------------------------- task actions

def day_summary(user, day):
    tasks = list(Task.objects.filter(user=user, date=day))
    counted = [t for t in tasks if t.status in (Task.Status.PENDING, Task.Status.DONE)]
    done = [t for t in counted if t.status == Task.Status.DONE]
    return {
        "done_minutes": sum(t.minutes for t in done),
        "planned_minutes": sum(t.minutes for t in counted),
        "done_count": len(done),
        "total_count": len(counted),
    }


def current_streak(user, today=None):
    today = today or timezone.localdate()
    rows = list(Task.objects.filter(user=user, date__lte=today, date__gte=today - timedelta(days=400)).values_list("date", "status"))
    done = {d for d, status in rows if status == Task.Status.DONE}
    planned = {d for d, _ in rows}
    rest = getattr(getattr(user, "student_profile", None), "rest_weekday", None)
    return compute_streak(done, planned, rest, today)


def _clean_counts(task, correct, wrong, blank):
    """Validate the optional correct/wrong/blank numbers; only practice and review tasks take them."""
    if task.kind not in (Task.Kind.PRACTICE, Task.Kind.REVIEW):
        return None
    values = []
    for value in (correct, wrong, blank):
        if value in (None, ""):
            values.append(None)
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise TaskError("Doğru, yanlış ve boş sayıları tam sayı olmalı.", 400)
        if number < 0:
            raise TaskError("Sayılar negatif olamaz.", 400)
        values.append(number)
    if all(v is None for v in values):
        return None
    limit = 2 * (task.question_target or 0)
    if sum(v or 0 for v in values) > limit:
        raise TaskError(f"Toplam sayı en fazla {limit} olabilir.", 400)
    return tuple(v or 0 for v in values)


def _initial_minutes(user, topic, row):
    """Learn / practice minutes a topic needs when its first block is done (from its level)."""
    info = TopicInfo(
        id=topic.pk, subject_id=topic.subject_id, subject_order=0, order=topic.order, name=topic.name,
        avg_questions=float(topic.avg_questions), learn_hours=float(topic.learn_hours),
    )
    need = build_need(info, TopicState(level=row.level, boost=row.boost))
    return round(need.learn_need), round(need.practice_need)


def _apply_progress(task, row, today, counts):
    """Move topic progress forward for a finished task; returns (undo info, learned now)."""
    undo = {"learn": 0, "practice": 0, "solved": 0, "correct": 0, "wrong": 0, "caused_learned": False, "was_state": row.state}
    answered = sum(counts) if counts else 0
    if answered:
        row.questions_solved += answered
        row.questions_correct += counts[0]
        row.questions_wrong += counts[1]
        undo.update(solved=answered, correct=counts[0], wrong=counts[1])

    if task.kind in (Task.Kind.LEARN, Task.Kind.PRACTICE) and row.state != TopicProgress.State.LEARNED:
        in_scope = PlanTopic.objects.filter(plan__user=task.user, plan__is_active=True, topic_id=row.topic_id, included=True).exists()
        if in_scope or row.remaining_learn_minutes is not None:
            if row.remaining_learn_minutes is None:
                row.remaining_learn_minutes, row.remaining_practice_minutes = _initial_minutes(task.user, task.topic, row)
            if task.kind == Task.Kind.LEARN:
                used = min(task.minutes, row.remaining_learn_minutes)
                row.remaining_learn_minutes -= used
                undo["learn"] = used
            else:
                used = min(task.minutes, row.remaining_practice_minutes)
                row.remaining_practice_minutes -= used
                undo["practice"] = used
                extra = extra_practice_minutes(*counts) if counts else 0
                if extra:  # weak accuracy: the topic needs more practice
                    row.remaining_practice_minutes += extra
                    undo["extra_practice"] = extra
            if row.state == TopicProgress.State.NOT_STARTED:
                row.state = TopicProgress.State.IN_PROGRESS
            if row.remaining_learn_minutes <= 0 and row.remaining_practice_minutes <= 0:
                row.state = TopicProgress.State.LEARNED
                row.learned_on = today
                undo["caused_learned"] = True
    return undo


@transaction.atomic
def complete_task(task, correct=None, wrong=None, blank=None, today=None):
    """Mark a task done (with optional results). Returns True when the future plan needs a refresh."""
    today = today or timezone.localdate()
    task = Task.objects.select_for_update(of=("self",)).select_related("topic", "user").get(pk=task.pk)
    if task.date > today:
        raise TaskError("Gelecekteki bir görevi henüz tamamlayamazsın.", 409)
    if task.status != Task.Status.PENDING:
        raise TaskError("Bu görev artık işaretlenemez.", 400)
    counts = _clean_counts(task, correct, wrong, blank)

    meta = {}
    refresh = False
    if task.topic_id:
        row = TopicProgress.objects.select_for_update().get(user=task.user, topic_id=task.topic_id)
        undo = _apply_progress(task, row, today, counts)
        row.save()
        meta["progress"] = undo
        exam_date = first_session(task.user.student_profile.exam).date

        if undo["caused_learned"]:
            first = first_review(today, exam_date)
            if first is not None:
                ReviewItem.objects.filter(user=task.user, topic_id=task.topic_id, is_active=True).update(is_active=False)
                item = ReviewItem.objects.create(user=task.user, topic_id=task.topic_id, interval_index=first[0], due_date=first[1])
                meta["created_review_item"] = item.pk
            refresh = True

        if task.kind == Task.Kind.REVIEW and task.review_item_id:
            item = ReviewItem.objects.select_for_update().get(pk=task.review_item_id)
            meta["review"] = {"interval_index": item.interval_index, "due_date": item.due_date.isoformat(), "is_active": item.is_active}
            accuracy = accuracy_of(*counts) if counts else None
            item.is_active, item.interval_index, item.due_date = after_review(item.interval_index, accuracy, today, exam_date)
            item.save()
            refresh = True

    task.status = Task.Status.DONE
    task.completed_at = timezone.now()
    if counts:
        task.correct, task.wrong, task.blank = counts
    task.meta = meta
    task.save()
    if refresh:
        regenerate_future(task.user, today)
    return refresh


def add_focus_time(task, seconds, today=None):
    """Add real study time (from the Pomodoro timer) to a task of today or an earlier day that is still open or done."""
    today = today or timezone.localdate()
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        raise TaskError("Süre tam sayı (saniye) olmalı.", 400)
    if not 1 <= seconds <= config.MAX_FOCUS_SECONDS_PER_REQUEST:
        raise TaskError("Süre geçerli bir aralıkta olmalı.", 400)
    if task.date > today:
        raise TaskError("Gelecekteki bir görev için süre tutulamaz.", 409)
    if task.status not in (Task.Status.PENDING, Task.Status.DONE):
        raise TaskError("Bu görev için süre tutulamaz.", 409)
    updated = Task.objects.filter(pk=task.pk, status__in=(Task.Status.PENDING, Task.Status.DONE)).update(
        focus_seconds=F("focus_seconds") + seconds)
    if not updated:
        raise TaskError("Bu görev için süre tutulamaz.", 409)
    return Task.objects.values_list("focus_seconds", flat=True).get(pk=task.pk)


def focus_seconds_between(user, first_day, last_day):
    """Total real study seconds of a user's tasks between two dates (inclusive)."""
    return Task.objects.filter(user=user, date__gte=first_day, date__lte=last_day).aggregate(
        total=Sum("focus_seconds"))["total"] or 0


@transaction.atomic
def skip_task(task, today=None):
    """The student will not do this task: its minutes stay queued and move to the next days."""
    today = today or timezone.localdate()
    task = Task.objects.select_for_update().get(pk=task.pk)
    if task.date > today:
        raise TaskError("Gelecekteki bir görevi henüz atlayamazsın.", 409)
    if task.status != Task.Status.PENDING:
        raise TaskError("Bu görev artık atlanamaz.", 400)
    task.status = Task.Status.SKIPPED
    task.save(update_fields=["status"])
    regenerate_future(task.user, today)


@transaction.atomic
def undo_task(task, today=None):
    """Take back a done or skipped task, only on the same day."""
    today = today or timezone.localdate()
    task = Task.objects.select_for_update(of=("self",)).select_related("topic", "user").get(pk=task.pk)
    if task.date != today:
        raise TaskError("Yalnızca bugünkü görevler geri alınabilir.", 409)
    if task.status not in (Task.Status.DONE, Task.Status.SKIPPED):
        raise TaskError("Bu görev geri alınamaz.", 400)

    refresh = task.status == Task.Status.SKIPPED
    if task.status == Task.Status.DONE:
        meta = task.meta or {}
        undo = meta.get("progress")
        if undo and task.topic_id:
            row = TopicProgress.objects.select_for_update().get(user=task.user, topic_id=task.topic_id)
            if undo["learn"] and row.remaining_learn_minutes is not None:
                row.remaining_learn_minutes += undo["learn"]
            if undo["practice"] and row.remaining_practice_minutes is not None:
                row.remaining_practice_minutes += undo["practice"] - undo.get("extra_practice", 0)
            row.questions_solved = max(0, row.questions_solved - undo["solved"])
            row.questions_correct = max(0, row.questions_correct - undo["correct"])
            row.questions_wrong = max(0, row.questions_wrong - undo["wrong"])
            if undo["caused_learned"]:
                row.state = TopicProgress.State.IN_PROGRESS
                row.learned_on = None
                refresh = True
            elif undo["was_state"] == TopicProgress.State.NOT_STARTED and row.state == TopicProgress.State.IN_PROGRESS:
                other_work = Task.objects.filter(
                    user=task.user, topic_id=task.topic_id, status=Task.Status.DONE,
                    kind__in=(Task.Kind.LEARN, Task.Kind.PRACTICE),
                ).exclude(pk=task.pk).exists()
                if not other_work:
                    row.state = TopicProgress.State.NOT_STARTED
            row.save()
        if meta.get("created_review_item"):
            ReviewItem.objects.filter(pk=meta["created_review_item"], user=task.user).delete()
        review = meta.get("review")
        if review and task.review_item_id:
            ReviewItem.objects.filter(pk=task.review_item_id).update(
                interval_index=review["interval_index"],
                due_date=date_cls.fromisoformat(review["due_date"]),
                is_active=review["is_active"],
            )
            refresh = True
    task.status = Task.Status.PENDING
    task.completed_at = None
    task.correct = task.wrong = task.blank = None
    task.meta = {}
    task.save()
    if refresh:
        regenerate_future(task.user, today)
