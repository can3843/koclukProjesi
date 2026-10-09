from datetime import timedelta

from django.test import TestCase

from planner.engine import config
from planner.models import Task, WeeklyReview
from planner.services import TaskError, add_focus_time, complete_task, create_weekly_review, skip_task

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, seed_catalog

D0 = FROZEN_TODAY
JSON = {"HTTP_ACCEPT": "application/json"}


class FocusTimeServiceTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.task = Task.objects.filter(user=self.user, date=D0).first()

    def test_time_adds_up(self):
        self.assertEqual(add_focus_time(self.task, 600, D0), 600)
        self.assertEqual(add_focus_time(self.task, 90, D0), 690)
        self.task.refresh_from_db()
        self.assertEqual(self.task.focus_seconds, 690)

    def test_bad_values_are_rejected(self):
        for value in (0, -5, "abc", None, "", config.MAX_FOCUS_SECONDS_PER_REQUEST + 1):
            with self.assertRaises(TaskError) as caught:
                add_focus_time(self.task, value, D0)
            self.assertEqual(caught.exception.status, 400, value)
        self.task.refresh_from_db()
        self.assertEqual(self.task.focus_seconds, 0)

    def test_the_largest_allowed_value_works(self):
        self.assertEqual(add_focus_time(self.task, config.MAX_FOCUS_SECONDS_PER_REQUEST, D0), config.MAX_FOCUS_SECONDS_PER_REQUEST)

    def test_done_tasks_can_still_get_time_but_skipped_and_missed_cannot(self):
        complete_task(self.task, today=D0)
        add_focus_time(self.task, 60, D0)  # the timer may send its last seconds after the task was ticked
        other = Task.objects.filter(user=self.user, date=D0, status=Task.Status.PENDING).first()
        skip_task(other, D0)
        with self.assertRaises(TaskError) as caught:
            add_focus_time(other, 60, D0)
        self.assertEqual(caught.exception.status, 409)
        other.status = Task.Status.MISSED
        other.save()
        with self.assertRaises(TaskError):
            add_focus_time(other, 60, D0)

    def test_future_tasks_get_no_time(self):
        future = Task.objects.filter(user=self.user, date__gt=D0).first()
        with self.assertRaises(TaskError) as caught:
            add_focus_time(future, 60, D0)
        self.assertEqual(caught.exception.status, 409)

    def test_earlier_days_still_count(self):
        self.assertEqual(add_focus_time(self.task, 60, D0 + timedelta(days=1)), 60)


class FocusEndpointTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.client.force_login(self.user)
        self.task = Task.objects.filter(user=self.user, date=D0).first()
        self.url = f"/gorev/{self.task.pk}/sure/"

    def test_json_response_has_task_total_and_day_total(self):
        response = self.client.post(self.url, {"seconds": 300}, **JSON)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["task"], {"id": self.task.pk, "focus_seconds": 300})
        self.assertEqual(body["day"]["focus_seconds"], 300)
        body = self.client.post(self.url, {"seconds": 120}, **JSON).json()
        self.assertEqual(body["task"]["focus_seconds"], 420)

    def test_invalid_seconds_is_400_with_turkish_error(self):
        response = self.client.post(self.url, {"seconds": "x"}, **JSON)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("saniye", response.json()["error"])

    def test_get_is_not_allowed_and_login_is_required(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, {"seconds": 60}, **JSON).status_code, 302)

    def test_somebody_elses_task_is_404_and_untouched(self):
        other, _ = make_onboarded_user("baska@example.com")
        theirs = Task.objects.filter(user=other, date=D0).first()
        response = self.client.post(f"/gorev/{theirs.pk}/sure/", {"seconds": 60}, **JSON)
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.focus_seconds, 0)

    def test_future_task_is_409(self):
        future = Task.objects.filter(user=self.user, date__gt=D0).first()
        self.assertEqual(self.client.post(f"/gorev/{future.pk}/sure/", {"seconds": 60}, **JSON).status_code, 409)

    def test_plain_form_post_redirects_to_today(self):
        response = self.client.post(self.url, {"seconds": 60})
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)
        self.task.refresh_from_db()
        self.assertEqual(self.task.focus_seconds, 60)


class FocusScreensTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.client.force_login(self.user)
        self.task = Task.objects.filter(user=self.user, date=D0).first()

    def test_today_has_focus_buttons_and_the_timer_panel(self):
        response = self.client.get("/bugun/")
        self.assertContains(response, "data-focus-start")
        self.assertContains(response, "⏱ Odaklan")
        self.assertContains(response, "data-timer")
        self.assertContains(response, f'data-focus="{config.POMODORO_FOCUS_MIN * 60}"')
        self.assertContains(response, "js/timer.js")

    def test_done_tasks_have_no_focus_button_but_show_their_time(self):
        add_focus_time(self.task, 25 * 60, D0)
        complete_task(self.task, today=D0)
        html = self.client.get("/bugun/").content.decode()
        card = html[html.index(f'id="task-{self.task.pk}"'):]
        card = card[:card.index("</article>")]
        self.assertNotIn("data-focus-start", card)
        self.assertIn("⏱ 25 dk", card)
        self.assertContains(self.client.get("/bugun/"), "odak")

    def test_week_view_has_no_focus_buttons_for_future_days(self):
        Task.objects.filter(user=self.user, date=D0).delete()
        self.assertNotContains(self.client.get("/hafta/"), "data-focus-start")

    def test_progress_shows_week_and_total_focus_time(self):
        add_focus_time(self.task, 90 * 60, D0)
        response = self.client.get("/ilerleme/")
        self.assertEqual(response.context["stats"]["focus_week"], 90 * 60)
        self.assertContains(response, "⏱ 1 sa 30 dk")
        self.assertEqual(response.context["weekly"]["rows"][-1]["focus_seconds"], 90 * 60)

    def test_weekly_review_includes_focus_minutes(self):
        add_focus_time(self.task, 45 * 60, D0)
        review = create_weekly_review(self.user, D0 + timedelta(days=7))
        self.assertIsInstance(review, WeeklyReview)
        self.assertEqual(review.stats["focus_minutes"], 45)
        response = self.client.get("/degerlendirme/")
        self.assertContains(response, "odaklanarak geçen süre")

    def test_plan_pace_does_not_depend_on_focus_time(self):
        from planner.services import compute_pace

        before = compute_pace(self.user, D0 + timedelta(days=5))
        add_focus_time(self.task, 3600, D0)
        self.assertEqual(compute_pace(self.user, D0 + timedelta(days=5)), before)
