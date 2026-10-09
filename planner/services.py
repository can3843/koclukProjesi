"""Bridge between the database and the pure plan engine (CLAUDE.md §6.1). Single entry points for views."""

from collections import defaultdict
from dataclasses import asdict
from datetime import date as date_cls, timedelta

from django.db import transaction
from django.utils import timezone

from catalog.models import ExamSession, ExamTest, Subject, Topic

from .engine import config, make_plan
from .engine.adaptation import compute_streak, missed_task_ids
from .engine.capacity import build_days
from .engine.needs import build_need, candidate_needs
from .engine.phases import phase_for
from .engine.reviews import accuracy_of, after_review, first_review
from .engine.scheduler import ReviewDue, ScheduleTopic, schedule
from .engine.types import MockResult, PlanInput, SessionInfo, SubjectInfo, TestInfo, TopicInfo, TopicState
from .models import MockExam, Plan, PlanTopic, ReviewItem, StudentProfile, Task, TopicProgress


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

def known_mock_dates(user):
    """Days of mocks that were taken, missed or are still planned (keeps the mock calendar stable)."""
    dates = set(Task.objects.filter(user=user, kind=Task.Kind.MOCK).values_list("date", flat=True))
    dates |= set(MockExam.objects.filter(user=user).values_list("taken_on", flat=True))
    return tuple(sorted(dates))


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
        known_mock_dates=known_mock_dates(user),
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

@transaction.atomic
def ensure_daily_state(user, today=None):
    """Lazy daily housekeeping, run when a student opens the app (§6.9). Returns notices for the UI."""
    today = today or timezone.localdate()
    profile = StudentProfile.objects.select_for_update().select_related("exam", "track").get(user=user)
    notices = {"missed": 0, "phase_changed": None}
    if profile.last_daily_sync == today or profile.exam_id is None:
        return notices

    # 1. tasks of days that are over and still pending become missed (their minutes stay queued)
    stale = list(Task.objects.filter(user=user, status=Task.Status.PENDING, date__lt=today).values_list("id", "date", "status"))
    missed_ids = missed_task_ids(stale, today)
    if missed_ids:
        Task.objects.filter(pk__in=missed_ids).update(status=Task.Status.MISSED)
    notices["missed"] = len(missed_ids)

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
        # 5. fill the window: days without any task get tasks (done work today is never regenerated)
        generate_tasks(user, plan, today)

    profile.last_daily_sync = today
    profile.save(update_fields=["last_daily_sync"])
    return notices


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
    task = Task.objects.select_for_update().select_related("topic", "user").get(pk=task.pk)
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
    task = Task.objects.select_for_update().select_related("topic", "user").get(pk=task.pk)
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
                row.remaining_practice_minutes += undo["practice"]
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
