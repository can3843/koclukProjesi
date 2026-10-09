from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase

from catalog.models import Topic
from planner.models import Plan, Task, TopicProgress
from planner.services import build_plan, get_active_plan

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, make_user, seed_catalog

D0 = FROZEN_TODAY
JSON = {"HTTP_ACCEPT": "application/json"}


class TodayPageTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.client.force_login(self.user)

    def test_today_page_shows_tasks_ring_streak_and_tabbar(self):
        response = self.client.get("/bugun/")
        self.assertEqual(response.status_code, 200)
        for text in ("Elif", "görev", "gün seri", "data-ring", 'class="tabbar"', "Önümüzdeki 7 güne bak"):
            self.assertContains(response, text)
        self.assertContains(response, "Bugün yapamayacağım")
        self.assertContains(response, "Sınava 166 gün")

    def test_task_cards_show_peak_label_in_the_students_peak_time(self):
        self.profile.peak_time = "evening"
        self.profile.save()
        response = self.client.get("/bugun/")
        self.assertContains(response, "Akşam verimli saatinde")

    def test_first_visit_of_a_new_day_shows_the_missed_card_once(self):
        with patch("django.utils.timezone.localdate", return_value=D0 + timedelta(days=1)):
            first = self.client.get("/bugun/")
            self.assertContains(first, "Dün çalışamadın, sorun değil")
            self.assertContains(first, "önümüzdeki günlere yaydım")
            second = self.client.get("/bugun/")
            self.assertNotContains(second, "Dün çalışamadın")
        self.assertTrue(Task.objects.filter(user=self.user, status=Task.Status.MISSED).exists())

    def test_at_most_two_info_cards(self):
        with patch("django.utils.timezone.localdate", return_value=D0 + timedelta(days=80)):
            response = self.client.get("/bugun/")
        self.assertLessEqual(response.content.decode().count('class="info-card'), 2)
        self.assertContains(response, "Yeni döneme geçtin: Kapanış")

    def test_estimated_exam_date_card(self):
        self.assertContains(self.client.get("/bugun/"), "Sınav tarihi tahmini")

    def test_rest_day_card(self):
        self.profile.rest_weekday = D0.weekday()
        self.profile.save()
        Task.objects.filter(user=self.user, date=D0).delete()
        response = self.client.get("/bugun/")
        self.assertContains(response, "Bugün dinlenme günün")

    def test_empty_day_message(self):
        Task.objects.filter(user=self.user, date=D0).delete()
        self.profile.refresh_from_db()
        from planner.models import StudentProfile
        StudentProfile.objects.filter(pk=self.profile.pk).update(last_daily_sync=D0)
        self.assertContains(self.client.get("/bugun/"), "Bugün için görev yok")

    def test_final_week_shows_the_exam_day_preparation_card(self):
        user, _ = make_onboarded_user("late@example.com")
        near = date(2027, 6, 14)
        with patch("django.utils.timezone.localdate", return_value=near):
            build_plan(user, today=near, reason=Plan.Reason.MANUAL)
            self.client.force_login(user)
            response = self.client.get("/bugun/")
        self.assertContains(response, "Sınav günü hazırlık")
        self.assertContains(response, "sınava giriş belgeni")
        self.assertContains(response, "Sınava 5 gün")

    def test_exam_day_has_no_tasks_and_a_good_luck_message(self):
        exam = date(2027, 6, 19)
        with patch("django.utils.timezone.localdate", return_value=exam):
            response = self.client.get("/bugun/")
        self.assertContains(response, "Sınav günü geldi")
        self.assertFalse(Task.objects.filter(user=self.user, date__gte=exam, status=Task.Status.PENDING).exists())

    def test_all_done_shows_the_celebration(self):
        from planner.services import complete_task
        for task in Task.objects.filter(user=self.user, date=D0):
            complete_task(task, today=D0)
        response = self.client.get("/bugun/")
        self.assertContains(response, "Bugünü tamamladın! Yarın görüşürüz")
        self.assertNotContains(response, "data-celebrate hidden")

    def test_week_page_lists_seven_days(self):
        response = self.client.get("/hafta/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Önümüzdeki 7 gün")
        self.assertContains(response, "Bugün")
        self.assertContains(response, "Yarın")
        self.assertEqual(response.content.decode().count('class="card week-day'), 7)

    def test_week_page_marks_the_rest_day(self):
        self.profile.rest_weekday = (D0 + timedelta(days=2)).weekday()
        self.profile.save()
        self.assertContains(self.client.get("/hafta/"), "Dinlenme günü")

    def test_pages_need_a_finished_onboarding(self):
        newcomer = make_user("c@example.com", "Can")
        self.client.force_login(newcomer)
        for path in ("/bugun/", "/hafta/"):
            self.assertRedirects(self.client.get(path), "/baslangic/1/", fetch_redirect_response=False)
        self.assertRedirects(self.client.post("/gorev/1/tamamla/"), "/baslangic/1/", fetch_redirect_response=False)


class TaskEndpointTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, _ = make_onboarded_user(weekday=180, weekend=300)
        self.client.force_login(self.user)
        self.today_tasks = list(Task.objects.filter(user=self.user, date=D0).order_by("order"))
        self.practice = next((t for t in Task.objects.filter(user=self.user) if t.kind in ("practice", "review")), None)

    def test_complete_json_response_matches_the_contract(self):
        task = self.today_tasks[0]
        response = self.client.post(f"/gorev/{task.pk}/tamamla/", **JSON)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["task"], {"id": task.pk, "status": "done"})
        self.assertEqual(set(body["day"]), {"done_minutes", "planned_minutes", "done_count", "total_count"})
        self.assertEqual(body["day"]["done_count"], 1)
        self.assertEqual(body["day"]["done_minutes"], task.minutes)
        self.assertEqual(body["day"]["total_count"], len(self.today_tasks))
        self.assertEqual(body["streak"], 1)
        self.assertIn("tamam", body["message"])
        self.assertIn("task-card is-done", body["html"])

    def test_last_task_gives_the_celebration_message(self):
        for task in self.today_tasks[:-1]:
            self.client.post(f"/gorev/{task.pk}/tamamla/", **JSON)
        body = self.client.post(f"/gorev/{self.today_tasks[-1].pk}/tamamla/", **JSON).json()
        self.assertEqual(body["message"], "Bugünü tamamladın! Yarın görüşürüz 👋")

    def test_complete_with_results_saves_them(self):
        practice = next(
            (t for t in Task.objects.filter(user=self.user, date=D0) if t.kind == "practice"), None
        )
        if practice is None:
            practice = Task.objects.create(
                user=self.user, plan=get_active_plan(self.user), date=D0, kind="practice",
                topic=Topic.objects.get(slug="tyt-matematik-uslu-sayilar"), subject_id=Topic.objects.get(slug="tyt-matematik-uslu-sayilar").subject_id,
                title="x", minutes=40, question_target=20, order=99,
            )
        response = self.client.post(f"/gorev/{practice.pk}/tamamla/", {"correct": "10", "wrong": "5", "blank": "2"}, **JSON)
        self.assertTrue(response.json()["ok"])
        practice.refresh_from_db()
        self.assertEqual((practice.correct, practice.wrong, practice.blank), (10, 5, 2))

    def test_skip_counts_option_ignores_the_numbers(self):
        practice = Task.objects.create(
            user=self.user, plan=get_active_plan(self.user), date=D0, kind="practice",
            topic=Topic.objects.get(slug="tyt-matematik-uslu-sayilar"),
            subject_id=Topic.objects.get(slug="tyt-matematik-uslu-sayilar").subject_id,
            title="x", minutes=40, question_target=20, order=98,
        )
        self.client.post(f"/gorev/{practice.pk}/tamamla/", {"correct": "10", "skip_counts": "1"}, **JSON)
        practice.refresh_from_db()
        self.assertIsNone(practice.correct)

    def test_invalid_numbers_are_400_with_a_turkish_message(self):
        practice = Task.objects.create(
            user=self.user, plan=get_active_plan(self.user), date=D0, kind="practice",
            topic=Topic.objects.get(slug="tyt-matematik-uslu-sayilar"),
            subject_id=Topic.objects.get(slug="tyt-matematik-uslu-sayilar").subject_id,
            title="x", minutes=40, question_target=20, order=97,
        )
        for data in ({"correct": "abc"}, {"correct": "-3"}, {"correct": "30", "wrong": "11"}):
            response = self.client.post(f"/gorev/{practice.pk}/tamamla/", data, **JSON)
            self.assertEqual(response.status_code, 400)
            body = response.json()
            self.assertFalse(body["ok"])
            self.assertTrue(body["error"])
        self.assertEqual(Task.objects.get(pk=practice.pk).status, "pending")

    def test_someone_elses_task_is_404(self):
        other, _ = make_onboarded_user("other@example.com")
        foreign = Task.objects.filter(user=other).first()
        for action in ("tamamla", "atla", "geri-al"):
            response = self.client.post(f"/gorev/{foreign.pk}/{action}/", **JSON)
            self.assertEqual(response.status_code, 404, action)
        self.assertEqual(Task.objects.get(pk=foreign.pk).status, "pending")
        self.assertEqual(self.client.post("/gorev/999999/tamamla/", **JSON).status_code, 404)

    def test_future_task_cannot_be_completed_409(self):
        future = Task.objects.filter(user=self.user, date=D0 + timedelta(days=2)).first()
        response = self.client.post(f"/gorev/{future.pk}/tamamla/", **JSON)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(Task.objects.get(pk=future.pk).status, "pending")

    def test_completed_task_cannot_be_completed_again(self):
        task = self.today_tasks[0]
        self.client.post(f"/gorev/{task.pk}/tamamla/", **JSON)
        self.assertEqual(self.client.post(f"/gorev/{task.pk}/tamamla/", **JSON).status_code, 400)

    def test_undo_and_skip_endpoints(self):
        task = self.today_tasks[0]
        self.client.post(f"/gorev/{task.pk}/tamamla/", **JSON)
        body = self.client.post(f"/gorev/{task.pk}/geri-al/", **JSON).json()
        self.assertEqual(body["task"]["status"], "pending")
        self.assertEqual(body["day"]["done_count"], 0)
        body = self.client.post(f"/gorev/{task.pk}/atla/", **JSON).json()
        self.assertEqual(body["task"]["status"], "skipped")
        self.assertEqual(body["day"]["total_count"], len(self.today_tasks) - 1)
        self.assertIn("önümüzdeki günlere yaydım", body["message"])

    def test_undo_is_only_possible_on_the_same_day(self):
        task = self.today_tasks[0]
        self.client.post(f"/gorev/{task.pk}/tamamla/", **JSON)
        with patch("django.utils.timezone.localdate", return_value=D0 + timedelta(days=1)):
            response = self.client.post(f"/gorev/{task.pk}/geri-al/", **JSON)
        self.assertEqual(response.status_code, 409)

    def test_form_fallback_redirects_to_today_with_a_message(self):
        task = self.today_tasks[0]
        response = self.client.post(f"/gorev/{task.pk}/tamamla/")
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)
        self.assertEqual(Task.objects.get(pk=task.pk).status, "done")
        page = self.client.get("/bugun/")
        self.assertContains(page, "tamam")

    def test_form_fallback_error_redirects_with_a_message(self):
        future = Task.objects.filter(user=self.user, date=D0 + timedelta(days=2)).first()
        response = self.client.post(f"/gorev/{future.pk}/tamamla/")
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/bugun/"), "henüz tamamlayamazsın")

    def test_get_is_not_allowed_and_guests_are_sent_to_login(self):
        task = self.today_tasks[0]
        self.assertEqual(self.client.get(f"/gorev/{task.pk}/tamamla/").status_code, 405)
        self.client.logout()
        response = self.client.post(f"/gorev/{task.pk}/tamamla/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/giris/", response["Location"])

    def test_topic_progress_moves_when_a_learn_task_is_done_through_the_endpoint(self):
        learn = next(t for t in self.today_tasks if t.kind == "learn")
        self.client.post(f"/gorev/{learn.pk}/tamamla/", **JSON)
        row = TopicProgress.objects.get(user=self.user, topic=learn.topic)
        self.assertEqual(row.state, "in_progress")
        self.assertIsNotNone(row.remaining_learn_minutes)

    def test_csrf_is_enforced(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        response = strict.post(f"/gorev/{self.today_tasks[0].pk}/tamamla/", **JSON)
        self.assertEqual(response.status_code, 403)
