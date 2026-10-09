from django.test import TestCase

from catalog.models import Topic
from planner.models import MockExam, MockScore, Plan, PlanTopic, TopicProgress
from planner.services import build_plan, exam_countdown, get_active_plan
from catalog.models import Subject

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, seed_catalog


class BuildPlanTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def test_build_plan_creates_active_plan_with_topics(self):
        user, profile = make_onboarded_user(build=False)
        plan = build_plan(user, today=FROZEN_TODAY, reason=Plan.Reason.ONBOARDING)
        self.assertTrue(plan.is_active)
        self.assertEqual(plan.phase_code, "P6")
        self.assertEqual(plan.days_left, 166)
        track_topic_count = Topic.objects.filter(is_active=True, subject__test__tracks=profile.track).distinct().count()
        self.assertEqual(plan.plan_topics.count(), track_topic_count)
        self.assertGreater(plan.plan_topics.filter(included=True).count(), 0)
        for key in ("raw_total", "new_any", "new_small", "practice", "review", "fits_all", "exam_date"):
            self.assertIn(key, plan.budget)

    def test_new_plan_deactivates_the_old_one(self):
        user, _ = make_onboarded_user()
        first = get_active_plan(user)
        second = build_plan(user, today=FROZEN_TODAY, reason=Plan.Reason.MANUAL)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(Plan.objects.filter(user=user, is_active=True).count(), 1)
        self.assertEqual(get_active_plan(user), second)

    def test_progress_rows_are_created_with_default_level_zero(self):
        user, profile = make_onboarded_user()
        rows = TopicProgress.objects.filter(user=user)
        self.assertGreater(rows.count(), 100)
        self.assertEqual(set(rows.values_list("level", flat=True)), {0})

    def test_included_topics_never_miss_an_unfinished_prerequisite(self):
        user, _ = make_onboarded_user(weekday=90, weekend=120)
        plan = get_active_plan(user)
        included = set(plan.plan_topics.filter(included=True).values_list("topic_id", flat=True))
        for topic in Topic.objects.filter(pk__in=included).prefetch_related("prerequisites"):
            for prereq in topic.prerequisites.all():
                level = TopicProgress.objects.filter(user=user, topic=prereq).values_list("level", flat=True).first()
                outside_track = level is None
                self.assertTrue(prereq.pk in included or outside_track or level == 2, f"{topic.slug} needs {prereq.slug}")

    def test_sequence_is_unique_and_contiguous_for_included_topics(self):
        user, _ = make_onboarded_user()
        sequence = sorted(PlanTopic.objects.filter(plan=get_active_plan(user), included=True).values_list("sequence", flat=True))
        self.assertEqual(sequence, list(range(1, len(sequence) + 1)))

    def test_levels_change_the_plan(self):
        user, profile = make_onboarded_user(weekday=60, weekend=90)
        before = get_active_plan(user).required_minutes
        TopicProgress.objects.filter(user=user).update(level=2, initial_level=2)
        after = build_plan(user, today=FROZEN_TODAY).required_minutes
        self.assertLess(after, before)

    def test_projection_json_has_sessions_tests_and_scenario(self):
        user, _ = make_onboarded_user()
        projection = get_active_plan(user).projection
        self.assertEqual([s["code"] for s in projection["sessions"]], ["TYT", "AYT"])
        self.assertEqual(len(projection["tests"]), 6)
        self.assertIn("plus_hour", projection)
        for session in projection["sessions"]:
            self.assertLessEqual(session["high"], session["question_count"])
            self.assertLessEqual(session["low"], session["high"])

    def test_mock_results_feed_the_calibration(self):
        user, profile = make_onboarded_user()
        base = get_active_plan(user).projection["sessions"][0]
        tyt = profile.track.tests.get(slug="tyt-turkce").session
        mock = MockExam.objects.create(user=user, session=tyt, taken_on=FROZEN_TODAY)
        for subject in Subject.objects.filter(test__session=tyt, test__tracks=profile.track):
            MockScore.objects.create(mock=mock, subject=subject, correct=subject.question_count, wrong=0, blank=0)
        calibrated = build_plan(user, today=FROZEN_TODAY).projection["sessions"][0]
        self.assertGreater(calibrated["high"], base["high"])
        self.assertLessEqual(calibrated["high"], calibrated["question_count"])

    def test_plans_of_two_users_are_independent(self):
        a, _ = make_onboarded_user("a@example.com", weekday=60, weekend=60)
        b, _ = make_onboarded_user("b@example.com", weekday=600, weekend=660)
        self.assertNotEqual(get_active_plan(a).budget["raw_total"], get_active_plan(b).budget["raw_total"])
        self.assertEqual(Plan.objects.filter(user=a).count(), 1)

    def test_other_tracks_use_their_own_tests(self):
        user, profile = make_onboarded_user(track="DIL")
        projection = get_active_plan(user).projection
        self.assertEqual([s["code"] for s in projection["sessions"]], ["TYT", "YDT"])

    def test_exam_countdown_reports_days_and_estimate_flag(self):
        _, profile = make_onboarded_user(build=False)
        info = exam_countdown(profile, today=FROZEN_TODAY)
        self.assertEqual(info["days"], 166)
        self.assertTrue(info["estimated"])
