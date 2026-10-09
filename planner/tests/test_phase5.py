"""Mocks, weak topics, boosts, pace, scope suggestion and weekly reviews against the database."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from catalog.models import Subject, Topic
from planner.engine import config
from planner.models import MockExam, MockScore, Plan, PlanTopic, ReviewItem, StudentProfile, Task, TopicProgress, WeeklyReview
from planner.services import (
    active_rescope_ids, add_topic_to_plan, apply_rescope, complete_task, compute_pace, compute_rescope, create_weekly_review,
    ensure_daily_state, get_active_plan, plan_suggestions, record_mock, set_weak_topics, snooze_rescope, unseen_review,
)

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, seed_catalog

D0 = FROZEN_TODAY


def topic(slug):
    return Topic.objects.get(slug=slug)


def row(user, slug):
    return TopicProgress.objects.get(user=user, topic__slug=slug)


def make_task(user, day, kind="practice", slug="tyt-matematik-uslu-sayilar", minutes=40, status="pending", target=20, order=1, **extra):
    t = topic(slug)
    return Task.objects.create(
        user=user, plan=get_active_plan(user), date=day, kind=kind, topic=t, subject=t.subject, title="x",
        minutes=minutes, question_target=target, order=order, status=status, **extra,
    )


def scores(*pairs):
    return {Subject.objects.get(slug=slug): values for slug, values in pairs}


class PaceAndWeakAccuracyTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, _ = make_onboarded_user()
        self.slug = "tyt-matematik-uslu-sayilar"

    def test_pace_needs_three_days_of_history_and_ignores_today(self):
        Task.objects.filter(user=self.user).delete()
        for offset in (1, 2):
            make_task(self.user, D0 - timedelta(days=offset), status="done", order=offset)
        self.assertIsNone(compute_pace(self.user, D0))
        make_task(self.user, D0 - timedelta(days=3), status="missed", order=3)
        make_task(self.user, D0, status="pending", order=4, minutes=500)  # today does not count
        self.assertAlmostEqual(compute_pace(self.user, D0), 2 / 3)

    def test_skipped_and_pending_tasks_count_as_planned(self):
        Task.objects.filter(user=self.user).delete()
        make_task(self.user, D0 - timedelta(days=1), status="done", order=1)
        make_task(self.user, D0 - timedelta(days=2), status="skipped", order=2)
        make_task(self.user, D0 - timedelta(days=3), status="pending", order=3)
        self.assertAlmostEqual(compute_pace(self.user, D0), 1 / 3)

    def test_weak_practice_accuracy_adds_extra_practice_and_undo_removes_it(self):
        TopicProgress.objects.filter(user=self.user, topic__slug=self.slug).update(
            state="in_progress", remaining_learn_minutes=0, remaining_practice_minutes=120)
        task = make_task(self.user, D0)
        complete_task(task, 5, 10, 5, today=D0)  # 25% correct
        self.assertEqual(row(self.user, self.slug).remaining_practice_minutes, 120 - 40 + config.EXTRA_PRACTICE_MIN)
        from planner.services import undo_task
        undo_task(task, today=D0)
        self.assertEqual(row(self.user, self.slug).remaining_practice_minutes, 120)

    def test_good_accuracy_adds_nothing_and_it_cannot_make_the_topic_learned_early(self):
        TopicProgress.objects.filter(user=self.user, topic__slug=self.slug).update(
            state="in_progress", remaining_learn_minutes=0, remaining_practice_minutes=40)
        task = make_task(self.user, D0)
        complete_task(task, 5, 10, 5, today=D0)  # weak: the 40 minutes are replaced by 40 extra minutes
        self.assertEqual(row(self.user, self.slug).state, "in_progress")
        self.assertFalse(ReviewItem.objects.filter(user=self.user).exists())


class MockRecordingTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=420)
        self.tyt = self.profile.track.tests.get(slug="tyt-turkce").session

    def test_record_mock_saves_scores_net_and_rebuilds_the_plan(self):
        before = get_active_plan(self.user)
        mock = record_mock(self.user, self.tyt, D0, scores(("tyt-turkce", (30, 4, 6)), ("tyt-matematik", (20, 8, 2))), today=D0)
        self.assertEqual(mock.scores.count(), 2)
        self.assertEqual(float(MockScore.objects.get(mock=mock, subject__slug="tyt-turkce").net), 29.0)
        self.assertEqual(float(MockScore.objects.get(mock=mock, subject__slug="tyt-matematik").net), 18.0)
        after = get_active_plan(self.user)
        self.assertNotEqual(before.pk, after.pk)
        self.assertEqual(Plan.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_a_planned_mock_task_of_the_same_day_and_session_is_linked_and_done(self):
        mock_task = Task.objects.filter(user=self.user, kind="mock").order_by("date").first()
        day = mock_task.date
        with patch("django.utils.timezone.localdate", return_value=day):
            mock = record_mock(self.user, mock_task.session, day, scores(("tyt-turkce", (25, 5, 10))), today=day)
        mock_task.refresh_from_db()
        self.assertEqual(mock.task_id, mock_task.pk)
        self.assertEqual(mock_task.status, Task.Status.DONE)

    def test_another_day_or_session_is_not_linked(self):
        mock_task = Task.objects.filter(user=self.user, kind="mock").order_by("date").first()
        mock = record_mock(self.user, mock_task.session, D0, scores(("tyt-turkce", (25, 5, 10))), today=D0)
        self.assertIsNone(mock.task_id)
        self.assertFalse(Task.objects.filter(user=self.user, kind="mock", status=Task.Status.DONE).exists())

    def test_a_task_is_linked_only_once(self):
        mock_task = Task.objects.filter(user=self.user, kind="mock").order_by("date").first()
        day = mock_task.date
        with patch("django.utils.timezone.localdate", return_value=day):
            first = record_mock(self.user, mock_task.session, day, scores(("tyt-turkce", (25, 5, 10))), today=day)
            second = record_mock(self.user, mock_task.session, day, scores(("tyt-turkce", (26, 5, 9))), today=day)
        self.assertEqual(first.task_id, mock_task.pk)
        self.assertIsNone(second.task_id)

    def test_a_mock_result_moves_the_estimate(self):
        base = get_active_plan(self.user).projection["sessions"][0]["high"]
        record_mock(self.user, self.tyt, D0, scores(
            ("tyt-turkce", (40, 0, 0)), ("tyt-matematik", (30, 0, 0)), ("tyt-geometri", (10, 0, 0)),
            ("tyt-tarih", (5, 0, 0)), ("tyt-cografya", (5, 0, 0)), ("tyt-felsefe", (5, 0, 0)), ("tyt-din", (5, 0, 0)),
            ("tyt-fizik", (7, 0, 0)), ("tyt-kimya", (7, 0, 0)), ("tyt-biyoloji", (6, 0, 0))), today=D0)
        calibrated = get_active_plan(self.user).projection["sessions"][0]
        self.assertGreater(calibrated["high"], base)
        self.assertLessEqual(calibrated["high"], calibrated["question_count"])


class WeakTopicTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=60, weekend=90)
        self.tyt = self.profile.track.tests.get(slug="tyt-turkce").session
        self.mock = record_mock(self.user, self.tyt, D0, scores(
            ("tyt-matematik", (10, 15, 5)), ("tyt-fizik", (2, 3, 2))), today=D0)

    def weak(self, *slugs, mock=None):
        return set_weak_topics(self.user, mock or self.mock, [topic(s).pk for s in slugs], today=D0)

    def test_marking_a_topic_raises_its_boost_by_one_step(self):
        self.weak("tyt-matematik-uslu-sayilar")
        self.assertAlmostEqual(row(self.user, "tyt-matematik-uslu-sayilar").boost, 1.0 + config.BOOST_STEP)
        self.assertEqual(list(self.mock.weak_topics.values_list("slug", flat=True)), ["tyt-matematik-uslu-sayilar"])

    def test_saving_the_same_choice_again_does_not_boost_twice(self):
        self.weak("tyt-matematik-uslu-sayilar")
        self.weak("tyt-matematik-uslu-sayilar")
        self.assertAlmostEqual(row(self.user, "tyt-matematik-uslu-sayilar").boost, 1.25)

    def test_boost_never_goes_above_the_maximum_over_many_mocks(self):
        for i in range(6):
            mock = record_mock(self.user, self.tyt, D0, scores(("tyt-matematik", (10, 5, 5))), today=D0)
            self.weak("tyt-matematik-uslu-sayilar", mock=mock)
        self.assertEqual(row(self.user, "tyt-matematik-uslu-sayilar").boost, config.BOOST_MAX)

    def test_topics_of_other_subjects_are_ignored(self):
        chosen = self.weak("tyt-turkce-sozcukte-anlam")  # Türkçe was not part of this mock
        self.assertEqual(chosen, [])
        self.assertEqual(row(self.user, "tyt-turkce-sozcukte-anlam").boost, 1.0)

    def test_a_boosted_topic_is_worth_more_in_the_new_plan(self):
        slug = "tyt-matematik-uslu-sayilar"
        before = PlanTopic.objects.get(plan=get_active_plan(self.user), topic__slug=slug).gain
        self.weak(slug)
        after = PlanTopic.objects.get(plan=get_active_plan(self.user), topic__slug=slug).gain
        self.assertAlmostEqual(after, before * 1.25, places=3)

    def test_a_learned_topic_comes_back_for_review_tomorrow(self):
        slug = "tyt-matematik-uslu-sayilar"
        TopicProgress.objects.filter(user=self.user, topic__slug=slug).update(state="learned", learned_on=D0 - timedelta(days=10))
        ReviewItem.objects.create(user=self.user, topic=topic(slug), interval_index=2, due_date=D0 + timedelta(days=25))
        self.weak(slug)
        item = ReviewItem.objects.get(user=self.user, topic__slug=slug, is_active=True)
        self.assertEqual(item.due_date, D0 + timedelta(days=1))

    def test_a_learned_topic_without_a_review_gets_one(self):
        slug = "tyt-matematik-koklu-sayilar"
        TopicProgress.objects.filter(user=self.user, topic__slug=slug).update(state="learned", learned_on=D0 - timedelta(days=40))
        self.weak(slug)
        self.assertEqual(ReviewItem.objects.get(user=self.user, topic__slug=slug).due_date, D0 + timedelta(days=1))

    def test_small_topics_outside_the_plan_are_offered_and_can_be_added(self):
        plan = get_active_plan(self.user)
        outside = PlanTopic.objects.filter(plan=plan, included=False, topic__subject__slug="tyt-matematik",
                                           topic__learn_hours__lte=config.BIG_TOPIC_HOURS).first()
        self.assertIsNotNone(outside)
        self.weak(outside.topic.slug)
        suggestions = plan_suggestions(self.user, self.mock)
        self.assertIn(outside.topic, [t for t in suggestions])
        add_topic_to_plan(self.user, outside.topic, today=D0)
        self.assertEqual(row(self.user, outside.topic.slug).user_override, "force_include")
        self.assertTrue(PlanTopic.objects.get(plan=get_active_plan(self.user), topic=outside.topic).included)
        self.assertNotIn(outside.topic, plan_suggestions(self.user, self.mock))

    def test_big_topics_are_not_suggested(self):
        big = Topic.objects.filter(subject__slug="tyt-fizik", learn_hours__gt=config.BIG_TOPIC_HOURS).first()
        self.weak(big.slug)
        self.assertNotIn(big, plan_suggestions(self.user, self.mock))


class BoostDecayTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, _ = make_onboarded_user()
        self.slug = "tyt-matematik-uslu-sayilar"

    def sync_after(self, days):
        StudentProfile.objects.filter(user=self.user).update(last_daily_sync=D0)
        ensure_daily_state(self.user, D0 + timedelta(days=days))

    def test_boost_fades_by_a_tenth_per_week_boundary(self):
        TopicProgress.objects.filter(user=self.user, topic__slug=self.slug).update(boost=1.5)
        self.sync_after(7)
        self.assertAlmostEqual(row(self.user, self.slug).boost, 1.4)

    def test_no_decay_inside_the_same_week_and_never_below_one(self):
        TopicProgress.objects.filter(user=self.user, topic__slug=self.slug).update(boost=1.5)
        self.sync_after(3)  # Monday to Thursday
        self.assertAlmostEqual(row(self.user, self.slug).boost, 1.5)
        TopicProgress.objects.filter(user=self.user, topic__slug=self.slug).update(boost=1.05)
        self.sync_after(14)
        self.assertEqual(row(self.user, self.slug).boost, 1.0)

    def test_several_missed_weeks_fade_proportionally(self):
        TopicProgress.objects.filter(user=self.user, topic__slug=self.slug).update(boost=1.9)
        self.sync_after(21)
        self.assertAlmostEqual(row(self.user, self.slug).boost, 1.6)


class ScopeSuggestionTests(FrozenTodayMixin, TestCase):
    """Scenario 13: a low pace gives a suggestion, computing it changes nothing, only the student can apply it."""

    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=150, weekend=240)
        self.later = D0 + timedelta(days=5)  # four planned days passed without anything done

    def counts(self):
        return (
            Plan.objects.count(), Task.objects.count(), PlanTopic.objects.count(),
            list(TopicProgress.objects.order_by("pk").values_list("user_override", "boost")),
        )

    def test_a_low_pace_produces_a_proposal(self):
        ensure_daily_state(self.user, self.later)
        self.assertAlmostEqual(compute_pace(self.user, self.later), 0.0)
        profile = StudentProfile.objects.get(user=self.user)
        ids = active_rescope_ids(profile, self.later)
        self.assertTrue(ids)
        self.assertEqual(profile.rescope_proposal["pace"], 0.0)

    def test_computing_the_suggestion_changes_nothing(self):
        ensure_daily_state(self.user, self.later)
        before = self.counts()
        ids = compute_rescope(self.user, self.later)
        self.assertTrue(ids)
        self.assertEqual(self.counts(), before)

    def test_nothing_is_dropped_without_the_students_approval(self):
        ensure_daily_state(self.user, self.later)
        self.assertFalse(TopicProgress.objects.filter(user=self.user, user_override="force_exclude").exists())
        ensure_daily_state(self.user, self.later + timedelta(days=1))
        self.assertFalse(TopicProgress.objects.filter(user=self.user, user_override="force_exclude").exists())

    def test_approving_drops_the_topics_and_rebuilds_the_plan(self):
        ensure_daily_state(self.user, self.later)
        ids = compute_rescope(self.user, self.later)
        dropped = apply_rescope(self.user, self.later)
        self.assertEqual(dropped, ids)
        self.assertEqual(TopicProgress.objects.filter(user=self.user, user_override="force_exclude").count(), len(ids))
        plan = get_active_plan(self.user)
        self.assertEqual(plan.reason, Plan.Reason.RESCOPE)
        for pt in PlanTopic.objects.filter(plan=plan, topic_id__in=ids):
            self.assertEqual((pt.included, pt.reason_code), (False, "user_excluded"))
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(profile.rescope_proposal, {})

    def test_not_now_hides_it_for_a_week(self):
        ensure_daily_state(self.user, self.later)
        snooze_rescope(self.user, self.later)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(active_rescope_ids(profile, self.later + timedelta(days=6)), [])
        self.assertTrue(active_rescope_ids(profile, self.later + timedelta(days=7)))

    def test_a_good_pace_proposes_nothing(self):
        for day in range(5):
            for task in Task.objects.filter(user=self.user, date=D0 + timedelta(days=day)):
                Task.objects.filter(pk=task.pk).update(status="done")
        self.assertGreaterEqual(compute_pace(self.user, self.later), 1.0)
        self.assertEqual(compute_rescope(self.user, self.later), [])
        ensure_daily_state(self.user, self.later)
        self.assertEqual(StudentProfile.objects.get(user=self.user).rescope_proposal, {})

    def test_the_proposal_is_empty_on_the_first_days(self):
        ensure_daily_state(self.user, D0 + timedelta(days=1))
        self.assertEqual(StudentProfile.objects.get(user=self.user).rescope_proposal, {})


class WeeklyReviewTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=240)
        self.next_monday = D0 + timedelta(days=7)

    def finish_some(self, count=2):
        done = 0
        for task in Task.objects.filter(user=self.user, date__lt=self.next_monday, kind__in=("learn", "practice")).order_by("date", "order"):
            if done == count:
                break
            Task.objects.filter(pk=task.pk).update(status="done")
            done += 1

    def test_review_of_the_previous_week_is_created_once_on_the_first_visit_of_the_new_week(self):
        self.finish_some()
        ensure_daily_state(self.user, self.next_monday)
        review = WeeklyReview.objects.get(user=self.user)
        self.assertEqual(review.week_start, D0)
        planned = sum(Task.objects.filter(user=self.user, date__gte=D0, date__lt=self.next_monday).values_list("minutes", flat=True))
        done = sum(Task.objects.filter(user=self.user, date__gte=D0, date__lt=self.next_monday, status="done").values_list("minutes", flat=True))
        self.assertEqual(review.stats["planned_minutes"], planned)
        self.assertEqual(review.stats["done_minutes"], done)
        self.assertEqual(review.stats["percent"], round(100 * done / planned))
        self.assertTrue(review.message)
        StudentProfile.objects.filter(user=self.user).update(last_daily_sync=None)
        ensure_daily_state(self.user, self.next_monday + timedelta(days=1))
        self.assertEqual(WeeklyReview.objects.filter(user=self.user).count(), 1)

    def test_not_created_inside_the_week_or_without_tasks(self):
        ensure_daily_state(self.user, D0 + timedelta(days=3))
        self.assertFalse(WeeklyReview.objects.exists())
        Task.objects.filter(user=self.user).delete()
        self.assertIsNone(create_weekly_review(self.user, self.next_monday))

    def test_a_week_is_not_reviewed_twice(self):
        first = create_weekly_review(self.user, self.next_monday)
        again = create_weekly_review(self.user, self.next_monday)
        self.assertIsNotNone(first)
        self.assertIsNone(again)

    def test_message_tier_follows_the_percentage(self):
        review = create_weekly_review(self.user, self.next_monday)  # nothing done: 0 %
        self.assertEqual(review.stats["percent"], 0)
        self.assertIn("🌱", review.message)
        WeeklyReview.objects.all().delete()
        Task.objects.filter(user=self.user, date__lt=self.next_monday).update(status="done")
        review = create_weekly_review(self.user, self.next_monday)
        self.assertEqual(review.stats["percent"], 100)
        self.assertIn("🚀", review.message)

    def test_questions_accuracy_and_improvement_are_reported(self):
        slug = "tyt-matematik-uslu-sayilar"
        Task.objects.filter(user=self.user).delete()
        make_task(self.user, D0 - timedelta(days=3), status="done", correct=10, wrong=10, blank=0, order=1)  # 50 % last week
        make_task(self.user, D0 + timedelta(days=1), status="done", correct=15, wrong=5, blank=0, order=2)  # 75 % this week
        make_task(self.user, D0 + timedelta(days=2), status="missed", order=3)
        review = create_weekly_review(self.user, self.next_monday)
        self.assertEqual(review.stats["answered"], 20)
        self.assertEqual(review.stats["accuracy"], 75)
        self.assertEqual(review.stats["improved"], {"topic": topic(slug).name, "points": 25})
        self.assertIn("doğruluğun %25 arttı", review.message)

    def test_focus_subjects_come_from_boosted_topics(self):
        TopicProgress.objects.filter(user=self.user, topic__slug="tyt-fizik-optik").update(boost=1.5)
        TopicProgress.objects.filter(user=self.user, topic__slug="tyt-matematik-uslu-sayilar").update(boost=1.25)
        review = create_weekly_review(self.user, self.next_monday)
        self.assertEqual(review.stats["focus"], ["Fizik", "Matematik"])
        self.assertIn("Gelecek hafta odak derslerin: Fizik, Matematik.", review.message)

    def test_mock_change_between_two_mocks_of_the_same_session(self):
        tyt = self.profile.track.tests.get(slug="tyt-turkce").session
        MockExam.objects.all().delete()
        first = MockExam.objects.create(user=self.user, session=tyt, taken_on=D0 - timedelta(days=10))
        second = MockExam.objects.create(user=self.user, session=tyt, taken_on=D0 + timedelta(days=2))
        subject = Subject.objects.get(slug="tyt-turkce")
        MockScore.objects.create(mock=first, subject=subject, correct=20, wrong=4, blank=16)
        MockScore.objects.create(mock=second, subject=subject, correct=28, wrong=4, blank=8)
        review = create_weekly_review(self.user, self.next_monday)
        self.assertEqual(review.stats["mock_changes"], [{"session": "TYT", "before": 19.0, "after": 27.0, "change": 8.0}])

    def test_unseen_review_is_found_until_it_is_opened(self):
        create_weekly_review(self.user, self.next_monday)
        self.assertIsNotNone(unseen_review(self.user))
        self.client.force_login(self.user)
        with patch("django.utils.timezone.localdate", return_value=self.next_monday):
            page = self.client.get("/degerlendirme/")
        self.assertContains(page, "Haftalık değerlendirmeler")
        self.assertContains(page, "plan yapıldı")
        self.assertIsNone(unseen_review(self.user))
