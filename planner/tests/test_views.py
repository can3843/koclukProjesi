from django.test import TestCase

from catalog.models import Subject, Topic, Track
from planner.models import MockExam, MockScore, Plan, StudentProfile, TopicProgress
from planner.services import get_active_plan

from .helpers import FROZEN_TODAY, FrozenTodayMixin, make_onboarded_user, make_user, seed_catalog


class OnboardingFlowTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()
        cls.say = Track.objects.get(code="SAY")

    def setUp(self):
        super().setUp()
        self.user = make_user()
        self.client.force_login(self.user)

    def finish_steps_1_to_4(self, weekday=180, weekend=300, rest=""):
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.client.post("/baslangic/2/", {"weekday_minutes": weekday, "weekend_minutes": weekend})
        self.client.post("/baslangic/3/", {"peak_time": "evening", "rest_weekday": rest})
        self.client.get("/baslangic/4/")
        return self.client.post("/baslangic/4/", {"action": "next"})

    def test_guest_is_sent_to_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/baslangic/1/"), "/giris/?next=/baslangic/1/", fetch_redirect_response=False)

    def test_unfinished_user_is_redirected_to_current_step(self):
        for path in ("/bugun/", "/plan/", "/plan/rapor/"):
            self.assertRedirects(self.client.get(path), "/baslangic/1/", fetch_redirect_response=False)
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.assertRedirects(self.client.get("/bugun/"), "/baslangic/2/", fetch_redirect_response=False)

    def test_cannot_skip_ahead(self):
        self.assertRedirects(self.client.get("/baslangic/3/"), "/baslangic/1/", fetch_redirect_response=False)
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.assertRedirects(self.client.get("/baslangic/4/"), "/baslangic/2/", fetch_redirect_response=False)

    def test_invalid_step_number_is_404(self):
        self.assertEqual(self.client.get("/baslangic/6/").status_code, 404)
        self.assertEqual(self.client.get("/baslangic/0/").status_code, 404)

    def test_step_1_shows_exam_estimated_badge_and_tracks(self):
        response = self.client.get("/baslangic/1/")
        self.assertContains(response, "YKS 2027")
        self.assertContains(response, "tahmini tarih")
        for name in ("Sayısal", "Eşit Ağırlık", "Sözel", "Yabancı Dil"):
            self.assertContains(response, name)
        self.assertContains(response, "Yakında")

    def test_step_1_requires_a_track(self):
        response = self.client.post("/baslangic/1/", {})
        self.assertContains(response, "Lütfen bir alan seç.")
        response = self.client.post("/baslangic/1/", {"track": 99999})
        self.assertContains(response, "Geçerli bir alan seç.")

    def test_step_1_saves_track_and_creates_progress_rows(self):
        response = self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.assertRedirects(response, "/baslangic/2/", fetch_redirect_response=False)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual(profile.track, self.say)
        self.assertGreater(TopicProgress.objects.filter(user=self.user).count(), 100)

    def test_step_2_validates_minutes(self):
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        for data in ({"weekday_minutes": 45, "weekend_minutes": 120}, {"weekday_minutes": 700, "weekend_minutes": 120},
                     {"weekday_minutes": 120, "weekend_minutes": 700}, {"weekday_minutes": 0, "weekend_minutes": 120}):
            response = self.client.post("/baslangic/2/", data)
            self.assertEqual(response.status_code, 200, data)
            self.assertContains(response, "field-error")
        self.assertEqual(StudentProfile.objects.get(user=self.user).onboarding_step, 2)

    def test_step_2_shows_total_hours_and_heavy_warning_text(self):
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        response = self.client.get("/baslangic/2/")
        self.assertContains(response, "Sınava kadar yaklaşık")
        self.assertContains(response, "Bu çok yoğun bir tempo.")
        self.assertContains(response, "data-total")

    def test_step_3_saves_peak_time_and_rest_day(self):
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.client.post("/baslangic/2/", {"weekday_minutes": 120, "weekend_minutes": 240})
        self.client.post("/baslangic/3/", {"peak_time": "night", "rest_weekday": "6"})
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual((profile.peak_time, profile.rest_weekday), ("night", 6))
        self.client.get("/baslangic/3/")
        self.client.post("/baslangic/3/", {"peak_time": "night", "rest_weekday": ""})
        self.assertIsNone(StudentProfile.objects.get(user=self.user).rest_weekday)

    def test_step_3_rejects_unknown_peak_time(self):
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.client.post("/baslangic/2/", {"weekday_minutes": 120, "weekend_minutes": 240})
        response = self.client.post("/baslangic/3/", {"peak_time": "midnight"})
        self.assertEqual(response.status_code, 200)

    def test_step_4_lists_subjects_of_the_track_with_counters(self):
        self.client.post("/baslangic/1/", {"track": self.say.pk})
        self.client.post("/baslangic/2/", {"weekday_minutes": 120, "weekend_minutes": 240})
        self.client.post("/baslangic/3/", {"peak_time": "morning", "rest_weekday": ""})
        response = self.client.get("/baslangic/4/")
        self.assertContains(response, "konu işaretlendi")
        self.assertContains(response, "Fizik")
        self.assertNotContains(response, "Tarih-2")  # not part of the SAY track
        self.assertContains(response, "Hepsini:")

    def test_step_4_saves_levels_of_one_subject_as_json(self):
        self.finish_steps_1_to_4()
        subject = Subject.objects.get(slug="tyt-matematik")
        topics = list(Topic.objects.filter(subject=subject))
        data = {"subject": subject.pk, f"level_{topics[0].pk}": "2", f"level_{topics[1].pk}": "1", f"level_{topics[2].pk}": "0"}
        response = self.client.post("/baslangic/4/", data, HTTP_ACCEPT="application/json")
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["marked"], 2)
        levels = {p.topic_id: (p.level, p.initial_level) for p in TopicProgress.objects.filter(user=self.user, topic__subject=subject)}
        self.assertEqual(levels[topics[0].pk], (2, 2))
        self.assertEqual(levels[topics[1].pk], (1, 1))
        self.assertEqual(levels[topics[2].pk], (0, 0))

    def test_step_4_set_all_button_without_javascript(self):
        self.finish_steps_1_to_4()
        subject = Subject.objects.get(slug="tyt-fizik")
        response = self.client.post("/baslangic/4/", {"subject": subject.pk, "set_all": "1"})
        self.assertEqual(response.status_code, 302)
        levels = set(TopicProgress.objects.filter(user=self.user, topic__subject=subject).values_list("level", flat=True))
        self.assertEqual(levels, {1})

    def test_step_4_rejects_subject_outside_the_track(self):
        self.finish_steps_1_to_4()
        outside = Subject.objects.get(slug="ayt-tarih-2")
        response = self.client.post("/baslangic/4/", {"subject": outside.pk, "set_all": "2"}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post("/baslangic/4/", {"subject": "abc", "set_all": "2"}).status_code, 404)

    def test_step_4_ignores_invalid_levels(self):
        self.finish_steps_1_to_4()
        subject = Subject.objects.get(slug="tyt-kimya")
        topic = Topic.objects.filter(subject=subject).first()
        self.client.post("/baslangic/4/", {"subject": subject.pk, f"level_{topic.pk}": "9"})
        self.assertEqual(TopicProgress.objects.get(user=self.user, topic=topic).level, 0)

    def test_step_5_without_input_creates_plan_and_redirects_to_report(self):
        self.finish_steps_1_to_4()
        response = self.client.post("/baslangic/5/", {})
        self.assertRedirects(response, "/plan/rapor/", fetch_redirect_response=False)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertTrue(profile.is_onboarded)
        plan = get_active_plan(self.user)
        self.assertEqual(plan.reason, Plan.Reason.ONBOARDING)
        self.assertEqual(MockExam.objects.filter(user=self.user).count(), 0)

    def test_step_5_saves_goals_and_mock_results(self):
        self.finish_steps_1_to_4()
        math = Subject.objects.get(slug="tyt-matematik")
        turkce = Subject.objects.get(slug="tyt-turkce")
        data = {
            "target_department": "Tıp", "target_tyt_net": "95.5", "target_ayt_net": "60",
            "date_TYT": "2026-12-20",
            f"c_{turkce.pk}": 30, f"w_{turkce.pk}": 4, f"b_{turkce.pk}": 6,
            f"c_{math.pk}": 20, f"w_{math.pk}": 8,
        }
        self.assertRedirects(self.client.post("/baslangic/5/", data), "/plan/rapor/", fetch_redirect_response=False)
        profile = StudentProfile.objects.get(user=self.user)
        self.assertEqual((profile.target_department, float(profile.target_tyt_net)), ("Tıp", 95.5))
        mock = MockExam.objects.get(user=self.user)
        self.assertEqual(mock.session.code, "TYT")
        self.assertEqual(str(mock.taken_on), "2026-12-20")
        score = MockScore.objects.get(mock=mock, subject=turkce)
        self.assertEqual((score.correct, score.wrong, score.blank), (30, 4, 6))
        self.assertEqual(float(score.net), 29.0)
        self.assertEqual(MockExam.objects.filter(user=self.user, session__code="AYT").count(), 0)

    def test_step_5_rejects_totals_above_question_count(self):
        self.finish_steps_1_to_4()
        math = Subject.objects.get(slug="tyt-matematik")
        response = self.client.post("/baslangic/5/", {f"c_{math.pk}": 25, f"w_{math.pk}": 10})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "soruyu geçemez")
        self.assertEqual(MockExam.objects.count(), 0)
        self.assertFalse(StudentProfile.objects.get(user=self.user).is_onboarded)

    def test_step_5_rejects_future_mock_dates_and_too_high_targets(self):
        self.finish_steps_1_to_4()
        turkce = Subject.objects.get(slug="tyt-turkce")
        response = self.client.post("/baslangic/5/", {"date_TYT": "2027-02-01", f"c_{turkce.pk}": 10})
        self.assertContains(response, "gelecekte olamaz")
        response = self.client.post("/baslangic/5/", {"target_tyt_net": "121"})
        self.assertContains(response, "Hedef net en fazla 120")

    def test_finished_user_cannot_reopen_onboarding(self):
        self.finish_steps_1_to_4()
        self.client.post("/baslangic/5/", {})
        self.assertRedirects(self.client.get("/baslangic/1/"), "/plan/rapor/", fetch_redirect_response=False)

    def test_onboarding_pages_have_no_app_navigation(self):
        response = self.client.get("/baslangic/1/")
        self.assertNotContains(response, 'class="tabbar"')
        self.assertContains(response, "Çıkış yap")


class ReportAndRoadmapTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def test_report_sections_and_honest_labels(self):
        user, _ = make_onboarded_user(weekday=120, weekend=180)
        self.client.force_login(user)
        response = self.client.get("/plan/rapor/")
        self.assertEqual(response.status_code, 200)
        for text in ("Zaman", "İhtiyaç", "Karar", "Tahmini net aralığın", "Odaklanacağın ilk konular",
                     "Hadi başlayalım", "Bu bir tahmindir", "Sınava <strong>166 gün</strong>", "tarih tahmini"):
            self.assertContains(response, text)
        self.assertContains(response, "Bunları bırakıyoruz")
        self.assertContains(response, "saat istiyor")

    def test_report_says_so_when_time_is_short(self):
        user, _ = make_onboarded_user(weekday=60, weekend=60)
        self.client.force_login(user)
        self.assertContains(self.client.get("/plan/rapor/"), "Vaktin bütün konulara yetmiyor")

    def test_report_celebrates_when_time_is_enough(self):
        user, _ = make_onboarded_user(weekday=600, weekend=660, build=False)
        TopicProgress.objects.filter(user=user).delete()
        from planner.services import build_plan, ensure_progress_rows
        ensure_progress_rows(user, user.student_profile.track)
        TopicProgress.objects.filter(user=user).update(level=2, initial_level=2)
        build_plan(user, today=FROZEN_TODAY)
        self.client.force_login(user)
        response = self.client.get("/plan/rapor/")
        self.assertContains(response, "Vaktin yetiyor")
        self.assertNotContains(response, "Bunları bırakıyoruz")

    def test_report_compares_target_with_range(self):
        user, profile = make_onboarded_user(weekday=90, weekend=120)
        profile.target_tyt_net = 119
        profile.target_ayt_net = 0
        profile.save()
        self.client.force_login(user)
        response = self.client.get("/plan/rapor/")
        self.assertContains(response, "Hedefin bu planla iddialı.")
        self.assertContains(response, "Günde 1 saat fazla çalışırsan")
        self.assertContains(response, "Hedefini aşma ihtimalin var.")

    def test_roadmap_shows_phases_and_topics_in_order(self):
        user, _ = make_onboarded_user()
        self.client.force_login(user)
        response = self.client.get("/plan/")
        self.assertContains(response, "Temel inşa")
        self.assertContains(response, "Şu an buradasın")
        self.assertContains(response, "Raporu gör")
        self.assertContains(response, "hafta")

    def test_countdown_chip_with_estimated_badge_on_app_pages(self):
        user, _ = make_onboarded_user()
        self.client.force_login(user)
        response = self.client.get("/bugun/")
        self.assertContains(response, "Sınava 166 gün")
        self.assertContains(response, "tahmini")

    def test_plan_tab_is_active_on_plan_pages(self):
        user, _ = make_onboarded_user()
        self.client.force_login(user)
        self.assertContains(self.client.get("/plan/"), 'href="/plan/"')

    def test_users_only_see_their_own_plan_and_cannot_touch_others_progress(self):
        a, _ = make_onboarded_user("a@example.com", weekday=60, weekend=60)
        b, _ = make_onboarded_user("b@example.com", weekday=600, weekend=660)
        self.client.force_login(a)
        report_a = self.client.get("/plan/rapor/").content
        self.client.force_login(b)
        report_b = self.client.get("/plan/rapor/").content
        self.assertNotEqual(report_a, report_b)

        # a user without onboarding cannot read anyone's plan, they are sent to onboarding
        newcomer = make_user("c@example.com", "Can")
        self.client.force_login(newcomer)
        self.assertRedirects(self.client.get("/plan/rapor/"), "/baslangic/1/", fetch_redirect_response=False)

        # b's level changes never touch a's rows
        before = list(TopicProgress.objects.filter(user=a).order_by("topic_id").values_list("level", flat=True))
        profile_b = StudentProfile.objects.get(user=b)
        profile_b.onboarding_completed_at = None
        profile_b.onboarding_step = 4
        profile_b.save()
        self.client.force_login(b)
        subject = Subject.objects.get(slug="tyt-matematik")
        self.client.post("/baslangic/4/", {"subject": subject.pk, "set_all": "2"})
        after = list(TopicProgress.objects.filter(user=a).order_by("topic_id").values_list("level", flat=True))
        self.assertEqual(before, after)
        self.assertEqual(set(TopicProgress.objects.filter(user=b, topic__subject=subject).values_list("level", flat=True)), {2})
