"""Task generation, the lazy daily state and task actions against the database."""

from datetime import timedelta

from django.test import TestCase

from catalog.models import Topic
from planner.engine import config
from planner.models import Plan, ReviewItem, StudentProfile, Task, TopicProgress
from planner.services import (
    TaskError, complete_task, current_streak, day_summary, ensure_daily_state, generate_tasks, get_active_plan,
    regenerate_future, skip_task, undo_task,
)

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, seed_catalog

D0 = FROZEN_TODAY


def make_task(user, kind="learn", topic=None, day=D0, minutes=45, target=None, order=1, status="pending"):
    plan = get_active_plan(user)
    return Task.objects.create(
        user=user, plan=plan, date=day, kind=kind, topic=topic, subject=topic.subject if topic else None,
        title=f"{kind} görevi", minutes=minutes, question_target=target, order=order, status=status,
    )


def progress_of(user, topic):
    return TopicProgress.objects.get(user=user, topic=topic)


class GenerationTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def test_plan_creation_fills_the_next_seven_days(self):
        user, _ = make_onboarded_user(rest=6)
        dates = sorted(set(Task.objects.filter(user=user).values_list("date", flat=True)))
        expected = [D0 + timedelta(days=i) for i in range(config.WINDOW_DAYS) if (D0 + timedelta(days=i)).weekday() != 6]
        self.assertEqual(dates, expected)
        self.assertTrue(all(t.status == Task.Status.PENDING for t in Task.objects.filter(user=user)))
        self.assertEqual(set(Task.objects.filter(user=user).values_list("plan_id", flat=True)), {get_active_plan(user).pk})

    def test_scenario_7_rest_day_has_no_tasks(self):
        user, _ = make_onboarded_user(rest=2)
        self.assertFalse(Task.objects.filter(user=user, date__week_day=4).exists())  # Wednesday (Django: Sunday = 1)

    def test_scenario_9_days_stay_within_capacity(self):
        user, _ = make_onboarded_user(weekday=120, weekend=180)
        for day in {t.date for t in Task.objects.filter(user=user)}:
            tasks = Task.objects.filter(user=user, date=day)
            if tasks.filter(kind=Task.Kind.MOCK).exists():
                continue
            capacity = (180 if day.weekday() >= 5 else 120) * (1 - config.BUFFER_RATIO)
            self.assertLessEqual(sum(t.minutes for t in tasks), capacity + 5, day)

    def test_tasks_carry_titles_orders_subjects_and_peak_flags(self):
        user, _ = make_onboarded_user()
        tasks = list(Task.objects.filter(user=user, date=D0))
        self.assertTrue(tasks)
        self.assertEqual([t.order for t in tasks], list(range(1, len(tasks) + 1)))
        for task in tasks:
            self.assertTrue(task.title)
            self.assertIsNotNone(task.subject_id)
        learn = [t for t in tasks if t.kind == Task.Kind.LEARN]
        self.assertTrue(learn)
        self.assertTrue(all(t.is_peak for t in learn))

    def test_generating_twice_creates_no_duplicates(self):
        user, _ = make_onboarded_user()
        before = Task.objects.filter(user=user).count()
        generate_tasks(user, get_active_plan(user), D0)
        generate_tasks(user, get_active_plan(user), D0)
        self.assertEqual(Task.objects.filter(user=user).count(), before)

    def test_new_plan_replaces_pending_tasks_but_not_done_days(self):
        user, _ = make_onboarded_user()
        first = Task.objects.filter(user=user, date=D0).first()
        complete_task(first, today=D0)
        from planner.services import build_plan
        build_plan(user, today=D0, reason=Plan.Reason.MANUAL)
        today_tasks = Task.objects.filter(user=user, date=D0)
        self.assertIn(first.pk, [t.pk for t in today_tasks])
        self.assertEqual(Task.objects.get(pk=first.pk).status, Task.Status.DONE)
        self.assertEqual(Task.objects.filter(user=user, date=D0, plan=get_active_plan(user)).count(), 0)  # today kept as it was
        self.assertTrue(Task.objects.filter(user=user, date=D0 + timedelta(days=1), plan=get_active_plan(user)).exists())

    def test_mock_days_follow_the_calendar_and_are_stable_between_days(self):
        user, _ = make_onboarded_user(weekday=180, weekend=420)
        first_pass = sorted(Task.objects.filter(user=user, kind=Task.Kind.MOCK).values_list("date", "session__code"))
        self.assertTrue(first_pass)
        self.assertTrue(all(d.weekday() >= 5 for d, _ in first_pass))
        # tomorrow the same mocks are still where they were
        tomorrow = D0 + timedelta(days=1)
        ensure_daily_state(user, tomorrow)
        later = sorted(Task.objects.filter(user=user, kind=Task.Kind.MOCK, date__gte=tomorrow).values_list("date", "session__code"))
        self.assertEqual(later, [m for m in first_pass if m[0] >= tomorrow])


class DailyStateTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def test_scenario_idempotent_second_call_the_same_day_changes_nothing(self):
        user, profile = make_onboarded_user()
        ensure_daily_state(user, D0)
        count = Task.objects.filter(user=user).count()
        notices = ensure_daily_state(user, D0)
        self.assertEqual(Task.objects.filter(user=user).count(), count)
        self.assertEqual(notices, {"missed": 0, "phase_changed": None})
        profile.refresh_from_db()
        self.assertEqual(profile.last_daily_sync, D0)

    def test_two_calls_never_duplicate_tasks_on_a_new_day(self):
        user, _ = make_onboarded_user()
        day = D0 + timedelta(days=1)
        ensure_daily_state(user, day)
        count = Task.objects.filter(user=user).count()
        StudentProfile.objects.filter(user=user).update(last_daily_sync=None)  # as if two requests raced
        ensure_daily_state(user, day)
        self.assertEqual(Task.objects.filter(user=user).count(), count)
        pairs = list(Task.objects.filter(user=user).values_list("date", "order"))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_new_day_extends_the_window_by_one_day(self):
        user, _ = make_onboarded_user()
        last_before = Task.objects.filter(user=user).order_by("-date").first().date
        ensure_daily_state(user, D0 + timedelta(days=1))
        last_after = Task.objects.filter(user=user).order_by("-date").first().date
        self.assertGreater(last_after, last_before)

    def test_scenario_9_missed_day_returns_work_to_the_queue_without_piling_up(self):
        user, _ = make_onboarded_user(weekday=180, weekend=240)
        day1 = Task.objects.filter(user=user, date=D0)
        day1_ids = list(day1.values_list("pk", flat=True))
        learn_minutes = sum(t.minutes for t in day1 if t.kind == Task.Kind.LEARN)
        self.assertGreater(learn_minutes, 0)

        day2 = D0 + timedelta(days=1)
        notices = ensure_daily_state(user, day2)
        self.assertEqual(notices["missed"], len(day1_ids))
        self.assertEqual(set(Task.objects.filter(pk__in=day1_ids).values_list("status", flat=True)), {Task.Status.MISSED})
        # nothing was marked as progress, so the minutes are still queued
        topic_ids = {t.topic_id for t in day1 if t.kind == Task.Kind.LEARN}
        for row in TopicProgress.objects.filter(user=user, topic_id__in=topic_ids):
            self.assertIsNone(row.remaining_learn_minutes)
        # the lost work is planned again, spread over the next days, never above a day's capacity
        replanned = Task.objects.filter(user=user, date__gte=day2, status=Task.Status.PENDING)
        self.assertTrue(replanned.filter(kind=Task.Kind.LEARN, topic_id__in=topic_ids).exists())
        for day in {t.date for t in replanned}:
            tasks = replanned.filter(date=day)
            if tasks.filter(kind=Task.Kind.MOCK).exists():
                continue
            capacity = (240 if day.weekday() >= 5 else 180) * (1 - config.BUFFER_RATIO)
            self.assertLessEqual(sum(t.minutes for t in tasks), capacity + 5, day)

    def test_phase_change_rebuilds_the_plan(self):
        user, _ = make_onboarded_user()
        self.assertEqual(get_active_plan(user).phase_code, "P6")
        later = D0 + timedelta(days=80)  # 86 days before the exam: Kapanış
        notices = ensure_daily_state(user, later)
        self.assertEqual(notices["phase_changed"], "P3")
        plan = get_active_plan(user)
        self.assertEqual((plan.phase_code, plan.reason), ("P3", Plan.Reason.PHASE_CHANGE))
        self.assertEqual(Plan.objects.filter(user=user, is_active=True).count(), 1)
        self.assertTrue(Task.objects.filter(user=user, date=later).exists())

    def test_no_tasks_are_made_on_or_after_exam_day(self):
        user, profile = make_onboarded_user()
        exam_day = D0 + timedelta(days=166)
        ensure_daily_state(user, exam_day)
        self.assertFalse(Task.objects.filter(user=user, date__gte=exam_day).exists())


class CompleteTaskTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user()
        self.topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        self.row = progress_of(self.user, self.topic)

    def test_learn_task_reduces_remaining_and_starts_the_topic(self):
        task = make_task(self.user, "learn", self.topic, minutes=45)
        complete_task(task, today=D0)
        self.row.refresh_from_db()
        need = round(float(self.topic.learn_hours) * 60)
        self.assertEqual(self.row.remaining_learn_minutes, round(need * 0.4) - 45)
        self.assertEqual(self.row.remaining_practice_minutes, need - round(need * 0.4))
        self.assertEqual(self.row.state, TopicProgress.State.IN_PROGRESS)
        task.refresh_from_db()
        self.assertEqual((task.status, task.completed_at is not None), (Task.Status.DONE, True))

    def test_topic_becomes_learned_and_gets_a_review_for_tomorrow(self):
        TopicProgress.objects.filter(pk=self.row.pk).update(
            state=TopicProgress.State.IN_PROGRESS, remaining_learn_minutes=0, remaining_practice_minutes=40)
        task = make_task(self.user, "practice", self.topic, minutes=40, target=20)
        complete_task(task, 15, 3, 2, today=D0)
        self.row.refresh_from_db()
        self.assertEqual((self.row.state, self.row.learned_on), (TopicProgress.State.LEARNED, D0))
        item = ReviewItem.objects.get(user=self.user, topic=self.topic)
        self.assertEqual((item.interval_index, item.due_date, item.is_active), (0, D0 + timedelta(days=1), True))
        self.assertEqual((self.row.questions_solved, self.row.questions_correct, self.row.questions_wrong), (20, 15, 3))
        # the review shows up on tomorrow's list
        self.assertTrue(Task.objects.filter(user=self.user, kind=Task.Kind.REVIEW, date=D0 + timedelta(days=1), topic=self.topic).exists())

    def test_undo_restores_everything(self):
        TopicProgress.objects.filter(pk=self.row.pk).update(
            state=TopicProgress.State.IN_PROGRESS, remaining_learn_minutes=0, remaining_practice_minutes=40)
        task = make_task(self.user, "practice", self.topic, minutes=40, target=20)
        complete_task(task, 15, 3, 2, today=D0)
        undo_task(task, today=D0)
        self.row.refresh_from_db()
        self.assertEqual((self.row.state, self.row.remaining_practice_minutes, self.row.learned_on), (TopicProgress.State.IN_PROGRESS, 40, None))
        self.assertEqual((self.row.questions_solved, self.row.questions_correct, self.row.questions_wrong), (0, 0, 0))
        self.assertFalse(ReviewItem.objects.filter(user=self.user, topic=self.topic).exists())
        task.refresh_from_db()
        self.assertEqual((task.status, task.correct, task.completed_at), (Task.Status.PENDING, None, None))
        self.assertFalse(Task.objects.filter(user=self.user, kind=Task.Kind.REVIEW, topic=self.topic).exists())

    def test_undo_of_a_first_block_returns_the_topic_to_not_started(self):
        task = make_task(self.user, "learn", self.topic, minutes=45)
        complete_task(task, today=D0)
        undo_task(task, today=D0)
        self.row.refresh_from_db()
        self.assertEqual(self.row.state, TopicProgress.State.NOT_STARTED)

    def test_numbers_are_validated(self):
        task = make_task(self.user, "practice", self.topic, minutes=40, target=20)
        for bad in ((-1, 0, 0), ("abc", 0, 0), (30, 10, 1)):
            with self.assertRaises(TaskError) as ctx:
                complete_task(task, *bad, today=D0)
            self.assertEqual(ctx.exception.status, 400)
        complete_task(task, 40, 0, 0, today=D0)  # exactly 2 x the target is allowed
        self.assertEqual(Task.objects.get(pk=task.pk).correct, 40)

    def test_numbers_are_ignored_for_learn_tasks(self):
        task = make_task(self.user, "learn", self.topic)
        complete_task(task, 5, 5, 5, today=D0)
        task.refresh_from_db()
        self.assertIsNone(task.correct)
        self.row.refresh_from_db()
        self.assertEqual(self.row.questions_solved, 0)

    def test_future_and_finished_tasks_cannot_be_completed(self):
        future = make_task(self.user, "learn", self.topic, day=D0 + timedelta(days=1))
        with self.assertRaises(TaskError) as ctx:
            complete_task(future, today=D0)
        self.assertEqual(ctx.exception.status, 409)
        task = make_task(self.user, "learn", self.topic, order=9)
        complete_task(task, today=D0)
        with self.assertRaises(TaskError) as ctx:
            complete_task(task, today=D0)
        self.assertEqual(ctx.exception.status, 400)

    def test_mock_task_can_be_completed_without_topic(self):
        task = make_task(self.user, "mock", None, minutes=165)
        complete_task(task, today=D0)
        self.assertEqual(Task.objects.get(pk=task.pk).status, Task.Status.DONE)

    def test_practice_on_an_outside_topic_only_updates_statistics(self):
        outside = Topic.objects.get(slug="tyt-fizik-optik")
        row = progress_of(self.user, outside)
        task = make_task(self.user, "practice", outside, minutes=40, target=20)
        complete_task(task, 10, 5, 5, today=D0)
        row.refresh_from_db()
        self.assertEqual((row.questions_solved, row.state, row.remaining_practice_minutes), (20, TopicProgress.State.NOT_STARTED, None))


class SkipAndUndoTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, _ = make_onboarded_user()

    def test_skipping_moves_the_work_to_later_days(self):
        task = Task.objects.filter(user=self.user, date=D0, kind=Task.Kind.LEARN).first()
        skip_task(task, today=D0)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.SKIPPED)
        row = progress_of(self.user, task.topic)
        self.assertIsNone(row.remaining_learn_minutes)  # nothing was consumed
        # later days are regenerated and still contain that topic
        self.assertTrue(Task.objects.filter(user=self.user, date__gt=D0, kind=Task.Kind.LEARN, topic=task.topic).exists())

    def test_undo_of_a_skip_and_of_a_done_task_only_works_on_the_same_day(self):
        task = Task.objects.filter(user=self.user, date=D0).first()
        skip_task(task, today=D0)
        undo_task(task, today=D0)
        self.assertEqual(Task.objects.get(pk=task.pk).status, Task.Status.PENDING)
        complete_task(task, today=D0)
        with self.assertRaises(TaskError) as ctx:
            undo_task(task, today=D0 + timedelta(days=1))
        self.assertEqual(ctx.exception.status, 409)

    def test_pending_task_cannot_be_undone_and_future_cannot_be_skipped(self):
        task = Task.objects.filter(user=self.user, date=D0).first()
        with self.assertRaises(TaskError):
            undo_task(task, today=D0)
        future = Task.objects.filter(user=self.user, date=D0 + timedelta(days=1)).first()
        with self.assertRaises(TaskError) as ctx:
            skip_task(future, today=D0)
        self.assertEqual(ctx.exception.status, 409)


class ReviewTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, _ = make_onboarded_user()
        self.topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        TopicProgress.objects.filter(user=self.user, topic=self.topic).update(
            state=TopicProgress.State.LEARNED, learned_on=D0 - timedelta(days=1),
            remaining_learn_minutes=0, remaining_practice_minutes=0)

    def review_task(self, interval_index=0, due=D0):
        item = ReviewItem.objects.create(user=self.user, topic=self.topic, interval_index=interval_index, due_date=due)
        task = make_task(self.user, "review", self.topic, minutes=20, target=10)
        task.review_item = item
        task.save()
        return item, task

    def test_scenario_10_review_chain_is_1_7_30_days(self):
        item, task = self.review_task(0)
        complete_task(task, 8, 1, 1, today=D0)
        item.refresh_from_db()
        self.assertEqual((item.interval_index, item.due_date, item.is_active), (1, D0 + timedelta(days=7), True))
        second = make_task(self.user, "review", self.topic, minutes=20, target=10, order=2)
        second.review_item = item
        second.save()
        complete_task(second, today=D0)
        item.refresh_from_db()
        self.assertEqual((item.interval_index, item.due_date), (2, D0 + timedelta(days=30)))
        third = make_task(self.user, "review", self.topic, minutes=20, target=10, order=3)
        third.review_item = item
        third.save()
        complete_task(third, 10, 0, 0, today=D0)
        item.refresh_from_db()
        self.assertFalse(item.is_active)

    def test_scenario_10_failed_review_comes_back_in_three_days(self):
        item, task = self.review_task(1)
        complete_task(task, 3, 6, 1, today=D0)
        item.refresh_from_db()
        self.assertEqual((item.interval_index, item.due_date, item.is_active), (1, D0 + timedelta(days=config.REVIEW_RETRY_DAYS), True))
        self.assertTrue(Task.objects.filter(user=self.user, kind=Task.Kind.REVIEW, date=D0 + timedelta(days=3), review_item=item).exists())

    def test_scenario_10_no_review_is_created_after_the_exam(self):
        exam_day = D0 + timedelta(days=166)
        row = progress_of(self.user, self.topic)
        row.state, row.remaining_learn_minutes, row.remaining_practice_minutes = TopicProgress.State.IN_PROGRESS, 0, 40
        row.save()
        ReviewItem.objects.filter(user=self.user).delete()
        task = make_task(self.user, "practice", self.topic, day=exam_day - timedelta(days=1), minutes=40, target=20)
        complete_task(task, today=exam_day - timedelta(days=1))
        self.assertFalse(ReviewItem.objects.filter(user=self.user, topic=self.topic, is_active=True).exists())

    def test_undo_review_restores_the_interval(self):
        item, task = self.review_task(0)
        complete_task(task, 9, 0, 1, today=D0)
        undo_task(task, today=D0)
        item.refresh_from_db()
        self.assertEqual((item.interval_index, item.due_date, item.is_active), (0, D0, True))

    def test_due_reviews_are_scheduled_on_their_day(self):
        item = ReviewItem.objects.create(user=self.user, topic=self.topic, interval_index=0, due_date=D0 + timedelta(days=2))
        regenerate_future(self.user, D0)
        tasks = Task.objects.filter(user=self.user, kind=Task.Kind.REVIEW, review_item=item)
        self.assertEqual(tasks.count(), 1)
        self.assertGreaterEqual(tasks.first().date, D0 + timedelta(days=2))
        self.assertEqual(tasks.first().minutes, config.REVIEW_TASK_MIN)


class StreakTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def test_streak_counts_days_with_done_tasks_and_ignores_rest_days(self):
        user, _ = make_onboarded_user(rest=6)
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        # Fri 1 Jan 2027 ... Mon 4 Jan 2027, Sunday (3 Jan) is the rest day
        for day in (D0 - timedelta(days=3), D0 - timedelta(days=1), D0):
            task = make_task(user, "learn", topic, day=day, order=day.day)
            complete_task(task, today=day)
        self.assertEqual(current_streak(user, D0), 3)

    def test_a_planned_but_missed_day_breaks_the_streak(self):
        user, _ = make_onboarded_user()
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        make_task(user, "learn", topic, day=D0 - timedelta(days=2), status="missed")
        done = make_task(user, "learn", topic, day=D0, order=5)
        complete_task(done, today=D0)
        self.assertEqual(current_streak(user, D0), 1)

    def test_day_summary_counts_pending_and_done_only(self):
        user, _ = make_onboarded_user()
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        Task.objects.filter(user=user).delete()
        a = make_task(user, "learn", topic, minutes=45, order=1)
        make_task(user, "learn", topic, minutes=30, order=2)
        make_task(user, "learn", topic, minutes=20, order=3, status="skipped")
        complete_task(a, today=D0)
        self.assertEqual(day_summary(user, D0), {"done_minutes": 45, "planned_minutes": 75, "done_count": 1, "total_count": 2})
