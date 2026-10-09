from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from catalog.models import Subject, Topic
from planner.models import MockExam, MockScore, Plan, StudentProfile, Task, TopicProgress, WeeklyReview
from planner.services import ensure_daily_state, get_active_plan, record_mock

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, make_user, seed_catalog

D0 = FROZEN_TODAY


def sid(slug):
    return Subject.objects.get(slug=slug).pk


class MockPagesTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=420)
        self.client.force_login(self.user)

    def post_mock(self, code="TYT", **data):
        body = {"oturum": code, "taken_on": "2027-01-03"}
        body.update(data)
        return self.client.post("/deneme/ekle/", body)

    def test_empty_list_has_an_add_button(self):
        response = self.client.get("/deneme/")
        self.assertContains(response, "Henüz deneme girmedin")
        self.assertContains(response, "Deneme sonucu ekle")

    def test_the_tab_is_active_and_leads_to_the_list(self):
        self.assertContains(self.client.get("/bugun/"), 'href="/deneme/"')

    def test_choose_page_lists_the_sessions_of_the_track(self):
        response = self.client.get("/deneme/ekle/")
        self.assertContains(response, "TYT denemesi")
        self.assertContains(response, "AYT denemesi")
        self.assertNotContains(response, "YDT denemesi")

    def test_form_lists_the_subjects_of_that_session(self):
        response = self.client.get("/deneme/ekle/?oturum=TYT")
        self.assertContains(response, "Türkçe")
        self.assertContains(response, "Biyoloji")
        self.assertNotContains(response, "Tarih-2")
        self.assertEqual(self.client.get("/deneme/ekle/?oturum=YDT").status_code, 404)

    def test_saving_a_result_goes_to_the_weak_topics_step(self):
        response = self.post_mock(**{f"c_{sid('tyt-turkce')}": 30, f"w_{sid('tyt-turkce')}": 4, f"b_{sid('tyt-turkce')}": 6})
        mock = MockExam.objects.get(user=self.user)
        self.assertRedirects(response, f"/deneme/ekle/?zayif={mock.pk}", fetch_redirect_response=False)
        self.assertEqual(float(MockScore.objects.get(mock=mock).net), 29.0)

    def test_totals_above_the_question_count_are_rejected(self):
        response = self.post_mock(**{f"c_{sid('tyt-matematik')}": 25, f"w_{sid('tyt-matematik')}": 10})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "soruyu geçemez")
        self.assertEqual(MockExam.objects.count(), 0)

    def test_an_empty_form_future_date_and_bad_numbers_are_rejected(self):
        self.assertContains(self.post_mock(), "En az bir dersin sonucunu gir")
        self.assertContains(self.post_mock(taken_on="2027-02-01", **{f"c_{sid('tyt-turkce')}": 5}), "gelecekte olamaz")
        self.assertEqual(self.post_mock(**{f"c_{sid('tyt-turkce')}": -3}).status_code, 200)
        self.assertEqual(MockExam.objects.count(), 0)

    def test_weak_topics_step_saves_and_boosts(self):
        mock = record_mock(self.user, self.profile.track.tests.get(slug="tyt-turkce").session, D0,
                           {Subject.objects.get(slug="tyt-matematik"): (10, 15, 5)}, today=D0)
        page = self.client.get(f"/deneme/ekle/?zayif={mock.pk}")
        self.assertContains(page, "zorlandığın konuları işaretle")
        self.assertContains(page, "Üslü Sayılar")
        self.assertNotContains(page, "Sözcükte Anlam")  # Türkçe is not part of this mock
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        response = self.client.post("/deneme/ekle/", {"zayif": mock.pk, "weak": [topic.pk]})
        self.assertRedirects(response, f"/deneme/{mock.pk}/", fetch_redirect_response=False)
        self.assertEqual(TopicProgress.objects.get(user=self.user, topic=topic).boost, 1.25)

    def test_detail_shows_nets_weak_topics_and_suggestions(self):
        mock = record_mock(self.user, self.profile.track.tests.get(slug="tyt-turkce").session, D0,
                           {Subject.objects.get(slug="tyt-matematik"): (20, 8, 2)}, today=D0)
        page = self.client.get(f"/deneme/{mock.pk}/")
        self.assertContains(page, "TYT denemesi")
        self.assertContains(page, "18,00")
        self.assertContains(page, "Henüz konu işaretlemedin")
        listing = self.client.get("/deneme/")
        self.assertContains(listing, "18,00")
        self.assertContains(listing, "/ 30")

    def test_suggestion_button_adds_the_topic_to_the_plan(self):
        user, profile = make_onboarded_user("tight@example.com", weekday=60, weekend=90)
        self.client.force_login(user)
        tyt = profile.track.tests.get(slug="tyt-turkce").session
        plan = get_active_plan(user)
        outside = plan.plan_topics.filter(included=False, topic__subject__slug="tyt-matematik", topic__learn_hours__lte=6).first().topic
        mock = record_mock(user, tyt, D0, {Subject.objects.get(slug="tyt-matematik"): (10, 15, 5)}, today=D0)
        self.client.post("/deneme/ekle/", {"zayif": mock.pk, "weak": [outside.pk]})
        page = self.client.get(f"/deneme/{mock.pk}/")
        self.assertContains(page, "plana ekleyelim mi")
        self.assertContains(page, "Plana ekle")
        response = self.client.post(f"/deneme/{mock.pk}/konu-ekle/{outside.pk}/")
        self.assertRedirects(response, f"/deneme/{mock.pk}/", fetch_redirect_response=False)
        self.assertEqual(TopicProgress.objects.get(user=user, topic=outside).user_override, "force_include")

    def test_the_result_button_appears_on_a_done_mock_task_and_links_it(self):
        task = Task.objects.filter(user=self.user, kind="mock").order_by("date").first()
        day = task.date
        with patch("django.utils.timezone.localdate", return_value=day):
            self.client.post(f"/gorev/{task.pk}/tamamla/", HTTP_ACCEPT="application/json")
            page = self.client.get("/bugun/")
            self.assertContains(page, "Deneme sonucunu gir")
            self.assertContains(page, f"gorev={task.pk}")
            self.client.post("/deneme/ekle/", {
                "oturum": task.session.code, "gorev": task.pk, "taken_on": day.isoformat(),
                f"c_{sid('tyt-turkce')}": 20,
            })
            self.assertEqual(MockExam.objects.get(user=self.user).task_id, task.pk)
            self.assertNotContains(self.client.get("/bugun/"), "Deneme sonucunu gir")

    def test_other_users_cannot_see_or_change_a_mock(self):
        mock = record_mock(self.user, self.profile.track.tests.get(slug="tyt-turkce").session, D0,
                           {Subject.objects.get(slug="tyt-matematik"): (10, 15, 5)}, today=D0)
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        other, _ = make_onboarded_user("other@example.com")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/deneme/{mock.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/deneme/ekle/?zayif={mock.pk}").status_code, 404)
        self.assertEqual(self.client.post("/deneme/ekle/", {"zayif": mock.pk, "weak": [topic.pk]}).status_code, 404)
        self.assertEqual(self.client.post(f"/deneme/{mock.pk}/konu-ekle/{topic.pk}/").status_code, 404)
        self.assertEqual(TopicProgress.objects.get(user=self.user, topic=topic).boost, 1.0)
        self.assertNotContains(self.client.get("/deneme/"), "TYT denemesi")

    def test_add_topic_needs_a_weak_topic_of_that_mock_and_post(self):
        mock = record_mock(self.user, self.profile.track.tests.get(slug="tyt-turkce").session, D0,
                           {Subject.objects.get(slug="tyt-matematik"): (10, 15, 5)}, today=D0)
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        self.assertEqual(self.client.post(f"/deneme/{mock.pk}/konu-ekle/{topic.pk}/").status_code, 404)  # not marked weak
        self.assertEqual(self.client.get(f"/deneme/{mock.pk}/konu-ekle/{topic.pk}/").status_code, 405)


class ScopePagesTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=150, weekend=240)
        self.client.force_login(self.user)
        self.later = D0 + timedelta(days=5)

    def behind(self):
        """Four planned days passed without anything done, then the app is opened."""
        patcher = patch("django.utils.timezone.localdate", return_value=self.later)
        patcher.start()
        self.addCleanup(patcher.stop)
        return self.client.get("/bugun/")

    def test_card_is_first_and_links_to_the_suggestion(self):
        page = self.behind()
        self.assertContains(page, "Planın gerisinde kalıyorsun")
        self.assertContains(page, 'href="/plan/kapsam-onerisi/"')
        self.assertLessEqual(page.content.decode().count('class="info-card'), 2)
        content = page.content.decode()
        self.assertLess(content.index("Planın gerisinde"), content.index("Dün çalışamadın"))

    def test_page_lists_topics_and_changes_nothing_until_confirmed(self):
        self.behind()
        before = TopicProgress.objects.filter(user=self.user, user_override="force_exclude").count()
        page = self.client.get("/plan/kapsam-onerisi/")
        self.assertContains(page, "Planını gerçek tempona uyduralım mı?")
        self.assertContains(page, "sen onaylamadan hiçbir konu plandan çıkmaz")
        self.assertContains(page, "Planı güncelle")
        self.assertContains(page, "Şimdilik kalsın")
        self.assertEqual(TopicProgress.objects.filter(user=self.user, user_override="force_exclude").count(), before)
        self.assertEqual(Plan.objects.filter(user=self.user, reason=Plan.Reason.RESCOPE).count(), 0)

    def test_confirming_applies_it(self):
        self.behind()
        response = self.client.post("/plan/kapsam-onerisi/", {"action": "apply"})
        self.assertRedirects(response, "/bugun/", fetch_redirect_response=False)
        self.assertTrue(TopicProgress.objects.filter(user=self.user, user_override="force_exclude").exists())
        self.assertEqual(get_active_plan(self.user).reason, Plan.Reason.RESCOPE)
        self.assertContains(self.client.get("/plan/rapor/"), "Bunları bırakıyoruz")

    def test_not_now_hides_the_card(self):
        self.behind()
        self.client.post("/plan/kapsam-onerisi/", {"action": "later"})
        self.assertFalse(TopicProgress.objects.filter(user=self.user, user_override="force_exclude").exists())
        self.assertNotContains(self.client.get("/bugun/"), "Planın gerisinde kalıyorsun")

    def test_page_for_a_student_who_keeps_up_says_nothing_to_do(self):
        response = self.client.get("/plan/kapsam-onerisi/")
        self.assertContains(response, "Şu an kapsamı daraltmaya gerek yok")

    def test_login_and_onboarding_are_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/plan/kapsam-onerisi/").status_code, 302)
        newcomer = make_user("c@example.com", "Can")
        self.client.force_login(newcomer)
        self.assertRedirects(self.client.get("/plan/kapsam-onerisi/"), "/baslangic/1/", fetch_redirect_response=False)


class CardPriorityTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user()
        self.client.force_login(self.user)
        StudentProfile.objects.filter(user=self.user).update(last_daily_sync=D0)

    def test_scope_suggestion_beats_review_and_review_beats_the_estimated_date(self):
        WeeklyReview.objects.create(user=self.user, week_start=D0 - timedelta(days=7), stats={}, message="Güzel bir hafta geçirdin.")
        page = self.client.get("/bugun/").content.decode()
        self.assertIn("Güzel bir hafta geçirdin.", page)
        self.assertIn("Sınav tarihi tahmini", page)  # two cards fit: review + estimated date
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        StudentProfile.objects.filter(user=self.user).update(rescope_proposal={"topic_ids": [topic.pk], "pace": 0.4})
        page = self.client.get("/bugun/").content.decode()
        self.assertIn("Planın gerisinde kalıyorsun", page)
        self.assertIn("Güzel bir hafta geçirdin.", page)
        self.assertNotIn("Sınav tarihi tahmini", page)  # only two cards at a time
        self.assertLess(page.index("Planın gerisinde"), page.index("Güzel bir hafta"))

    def test_review_card_links_to_the_reviews_page(self):
        WeeklyReview.objects.create(user=self.user, week_start=D0 - timedelta(days=7), stats={}, message="Mesaj")
        self.assertContains(self.client.get("/bugun/"), 'href="/degerlendirme/"')

    def test_reviews_page_shows_stats_and_marks_them_seen(self):
        WeeklyReview.objects.create(
            user=self.user, week_start=D0 - timedelta(days=7),
            stats={"percent": 82, "done_minutes": 640, "answered": 120, "accuracy": 71, "streak": 5, "mock_changes": []},
            message="Güzel bir hafta geçirdin, planının %82'sini yaptın.")
        page = self.client.get("/degerlendirme/")
        for text in ("%82", "640 dk", "%71 doğruluk", "5", "Yeni"):
            self.assertContains(page, text)
        self.assertNotContains(self.client.get("/bugun/"), 'href="/degerlendirme/"')

    def test_reviews_are_private(self):
        WeeklyReview.objects.create(user=self.user, week_start=D0 - timedelta(days=7), stats={"percent": 99}, message="Gizli mesaj")
        other, _ = make_onboarded_user("other@example.com")
        self.client.force_login(other)
        self.assertNotContains(self.client.get("/degerlendirme/"), "Gizli mesaj")

    def test_empty_reviews_page(self):
        self.assertContains(self.client.get("/degerlendirme/"), "İlk değerlendirmen")

    def test_full_week_cycle_shows_the_review_card_on_monday(self):
        StudentProfile.objects.filter(user=self.user).update(last_daily_sync=None)
        monday = D0 + timedelta(days=7)
        with patch("django.utils.timezone.localdate", return_value=monday):
            page = self.client.get("/bugun/")
        self.assertContains(page, "/degerlendirme/")
        self.assertTrue(WeeklyReview.objects.filter(user=self.user, week_start=D0).exists())
