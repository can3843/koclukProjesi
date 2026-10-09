from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from catalog.models import Subject, Topic, Track
from planner import charts
from planner.models import MockExam, MockScore, Plan, StudentProfile, Task, TopicProgress
from planner.services import build_plan, complete_task, get_active_plan, record_mock

from .helpers import FROZEN_TODAY, PASSWORD, FrozenTodayMixin, make_onboarded_user, make_user, seed_catalog

D0 = FROZEN_TODAY
User = get_user_model()


def add_mock(user, code="TYT", taken_on=None, nets=None):
    """A mock with `correct` answers for every subject of the session (wrong/blank 0)."""
    from catalog.models import ExamSession

    session = ExamSession.objects.get(code=code)
    mock = MockExam.objects.create(user=user, session=session, taken_on=taken_on or D0 - timedelta(days=1))
    for subject in Subject.objects.filter(test__session=session, test__tracks=user.student_profile.track).distinct():
        MockScore.objects.create(mock=mock, subject=subject, correct=nets or 5, wrong=4, blank=0)
    return mock


class ChartGeometryTests(TestCase):
    def test_line_chart_with_one_point_is_centered_and_has_no_path_issue(self):
        chart = charts.line_chart([{"label": "3 Oca", "value": 40.0, "title": "t"}], cap=120)
        self.assertEqual(len(chart["dots"]), 1)
        self.assertEqual(chart["dots"][0]["x"], (chart["left"] + chart["right"]) / 2)

    def test_line_chart_stays_inside_the_plot_and_respects_the_cap(self):
        points = [{"label": str(i), "value": v, "title": ""} for i, v in enumerate([10.0, 55.5, 118.0])]
        chart = charts.line_chart(points, cap=120, goal=100)
        for dot in chart["dots"]:
            self.assertGreaterEqual(dot["y"], 0)
            self.assertLessEqual(dot["y"], chart["height"])
        self.assertTrue(chart["path"].startswith("M"))
        self.assertLessEqual(float(chart["yticks"][-1]["label"].replace(",", ".")), 120)
        self.assertIsNotNone(chart["goal"])

    def test_negative_net_gets_room_below_zero(self):
        chart = charts.line_chart([{"label": "a", "value": -3.0, "title": ""}, {"label": "b", "value": 8.0, "title": ""}], cap=40)
        self.assertTrue(any(t["label"].startswith("-") or t["label"].startswith("−") for t in chart["yticks"]))

    def test_bar_chart_draws_done_inside_planned(self):
        chart = charts.bar_chart([
            {"label": "w1", "done": 0, "planned": 0, "title": ""},
            {"label": "w2", "done": 3.0, "planned": 6.0, "title": ""},
        ])
        empty, full = chart["bars"]
        self.assertEqual((empty["planned_path"], empty["done_path"]), ("", ""))
        self.assertTrue(full["planned_path"] and full["done_path"])


class ProgressPageTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get("/ilerleme/"), "/giris/?next=/ilerleme/")

    def test_empty_state_has_map_and_prompts(self):
        response = self.client.get("/ilerleme/")
        self.assertContains(response, "Henüz deneme girmedin")
        self.assertContains(response, "Bu gidişle sınav günü")
        self.assertContains(response, "Bu bir tahmindir")
        self.assertContains(response, 'class="tabbar"')

    def test_topic_map_has_one_tile_per_track_topic_and_marks_learned(self):
        row = TopicProgress.objects.filter(user=self.user).first()
        row.state = TopicProgress.State.LEARNED
        row.save()
        response = self.client.get("/ilerleme/")
        tiles = sum(len(g["tiles"]) for g in response.context["groups"])
        self.assertEqual(tiles, TopicProgress.objects.filter(user=self.user).count())
        self.assertContains(response, "tile-learned")
        self.assertContains(response, "Öğrenildi")

    def test_projection_range_is_a_range_not_a_promise(self):
        rows = self.client.get("/ilerleme/").context["projection"]
        self.assertTrue(rows)
        for row in rows:
            self.assertLessEqual(row["low"], row["high"])
            self.assertLessEqual(row["high"], row["cap"])

    def test_net_chart_for_session_and_subject(self):
        add_mock(self.user, "TYT", D0 - timedelta(days=10), nets=10)
        add_mock(self.user, "TYT", D0 - timedelta(days=2), nets=15)
        response = self.client.get("/ilerleme/")
        self.assertContains(response, "series-line")
        self.assertEqual(len(response.context["net"]["chart"]["dots"]), 2)
        subject = Subject.objects.get(slug="tyt-turkce")
        response = self.client.get(f"/ilerleme/?oturum=TYT&ders={subject.pk}")
        self.assertEqual(response.context["net"]["subject"], subject)
        self.assertEqual(response.context["net"]["cap"], subject.question_count)

    def test_svg_and_css_numbers_use_decimal_points(self):
        """Turkish localisation turns 12.5 into "12,5", which is not valid in SVG attributes or CSS."""
        import re

        add_mock(self.user, "TYT", D0 - timedelta(days=10), nets=10)
        add_mock(self.user, "TYT", D0 - timedelta(days=2), nets=17)
        complete_task(Task.objects.filter(user=self.user, date=D0).first(), today=D0)
        html = self.client.get("/ilerleme/").content.decode()
        self.assertNotRegex(html, r'(?:x|y|cx|cy|x1|x2|y1|y2|d|points)="[^"]*\d,\d')
        self.assertNotRegex(html, r'style="[^"]*\d,\d+%')
        self.assertRegex(html, r'class="range-band" style="left: \d+(\.\d+)?%')

    def test_goal_line_is_drawn_for_the_total(self):
        self.profile.target_tyt_net = Decimal("80")
        self.profile.save()
        add_mock(self.user, "TYT")
        self.assertContains(self.client.get("/ilerleme/"), "goal-line")

    def test_unknown_query_values_fall_back_to_defaults(self):
        add_mock(self.user, "TYT")
        response = self.client.get("/ilerleme/?oturum=XXX&ders=abc")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["net"]["session"].code, "TYT")
        self.assertIsNone(response.context["net"]["subject"])

    def test_other_users_mocks_are_not_shown(self):
        other, _ = make_onboarded_user("baska@example.com")
        add_mock(other, "TYT")
        self.assertContains(self.client.get("/ilerleme/"), "Henüz deneme girmedin")

    def test_weekly_hours_count_done_tasks(self):
        task = Task.objects.filter(user=self.user, date=D0).first()
        complete_task(task, today=D0)
        response = self.client.get("/ilerleme/")
        self.assertContains(response, "bar-done")
        this_week = response.context["weekly"]["rows"][-1]
        self.assertEqual(this_week["done_minutes"], task.minutes)
        self.assertGreaterEqual(this_week["planned_minutes"], task.minutes)
        self.assertEqual(response.context["stats"]["week_minutes"], task.minutes)


class SettingsTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.client.force_login(self.user)

    def schedule(self, **overrides):
        data = {"section": "schedule", "weekday_minutes": 180, "weekend_minutes": 300, "peak_time": "morning", "rest_weekday": ""}
        data.update(overrides)
        return self.client.post("/ayarlar/", data)

    def test_page_shows_current_values(self):
        response = self.client.get("/ayarlar/")
        self.assertContains(response, 'value="180"')
        self.assertContains(response, "Hesabımı ve tüm verilerimi sil")
        self.assertContains(response, "data-theme-choice")

    def test_requires_onboarding(self):
        newcomer = make_user("yeni@example.com", "Yeni")
        self.client.force_login(newcomer)
        self.assertRedirects(self.client.get("/ayarlar/"), "/baslangic/1/")

    def test_changing_time_rebuilds_the_plan(self):
        before = get_active_plan(self.user)
        response = self.schedule(weekday_minutes=300)
        self.assertRedirects(response, "/ayarlar/")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.weekday_minutes, 300)
        plan = get_active_plan(self.user)
        self.assertNotEqual(plan.pk, before.pk)
        self.assertEqual(plan.reason, Plan.Reason.SETTINGS_CHANGE)
        self.assertEqual(Plan.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_saving_the_same_capacity_does_not_rebuild(self):
        before = get_active_plan(self.user)
        self.schedule(peak_time="night")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.peak_time, "night")
        self.assertEqual(get_active_plan(self.user).pk, before.pk)

    def test_rest_day_removes_that_days_tasks(self):
        tomorrow = D0 + timedelta(days=1)
        self.assertTrue(Task.objects.filter(user=self.user, date=tomorrow).exists())
        self.schedule(rest_weekday=str(tomorrow.weekday()))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.rest_weekday, tomorrow.weekday())
        self.assertFalse(Task.objects.filter(user=self.user, date=tomorrow).exists())

    def test_invalid_time_is_rejected_and_nothing_changes(self):
        response = self.schedule(weekday_minutes=45)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "30 dakikanın katı")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.weekday_minutes, 180)

    def test_changing_track_needs_confirmation(self):
        track = Track.objects.get(code="SOZ")
        response = self.client.post("/ayarlar/", {"section": "track", "track": track.pk})
        self.assertContains(response, "onaylamalısın")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.track.code, "SAY")

    def test_changing_track_keeps_shared_progress_and_replans(self):
        tyt_topic = Topic.objects.get(slug="tyt-mat-uslu-sayilar") if Topic.objects.filter(slug="tyt-mat-uslu-sayilar").exists() else Topic.objects.filter(subject__test__session__code="TYT").first()
        row = TopicProgress.objects.get(user=self.user, topic=tyt_topic)
        row.level = 2
        row.save()
        track = Track.objects.get(code="SOZ")
        self.client.post("/ayarlar/", {"section": "track", "track": track.pk, "confirm": "1"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.track, track)
        row.refresh_from_db()
        self.assertEqual(row.level, 2)
        plan = get_active_plan(self.user)
        self.assertEqual(plan.reason, Plan.Reason.SETTINGS_CHANGE)
        subjects = {pt.topic.subject.test.slug for pt in plan.plan_topics.select_related("topic__subject__test")}
        self.assertNotIn("ayt-fen", subjects)
        self.assertTrue(TopicProgress.objects.filter(user=self.user, topic__subject__test__slug="ayt-sosyal-2").exists())

    def test_levels_page_lists_topics_and_saves(self):
        response = self.client.get("/ayarlar/seviyeler/")
        self.assertContains(response, "Konu seviyelerin")
        rows = list(TopicProgress.objects.filter(user=self.user)[:3])
        data = {f"level_{r.topic_id}": 2 for r in rows}
        response = self.client.post("/ayarlar/seviyeler/", data)
        self.assertRedirects(response, "/ayarlar/seviyeler/")
        for r in rows:
            r.refresh_from_db()
            self.assertEqual(r.level, 2)
        self.assertEqual(get_active_plan(self.user).reason, Plan.Reason.LEVELS_CHANGED)

    def test_levels_ignore_bad_values_learned_topics_and_other_users(self):
        other, _ = make_onboarded_user("baska@example.com")
        learned, ordinary = list(TopicProgress.objects.filter(user=self.user)[:2])
        learned.state = TopicProgress.State.LEARNED
        learned.save()
        mine = TopicProgress.objects.filter(user=other, topic=ordinary.topic).get()
        before = get_active_plan(self.user).pk
        self.client.post("/ayarlar/seviyeler/", {f"level_{learned.topic_id}": 2, f"level_{ordinary.topic_id}": 9})
        learned.refresh_from_db()
        ordinary.refresh_from_db()
        mine.refresh_from_db()
        self.assertEqual((learned.level, ordinary.level, mine.level), (0, 0, 0))
        self.assertEqual(get_active_plan(self.user).pk, before)

    def test_topic_override_exclude_include_and_auto(self):
        plan = get_active_plan(self.user)
        included = plan.plan_topics.filter(included=True).first().topic
        response = self.client.post(f"/ayarlar/konu/{included.pk}/", {"override": "force_exclude"})
        self.assertEqual(response.status_code, 302)
        row = TopicProgress.objects.get(user=self.user, topic=included)
        self.assertEqual(row.user_override, "force_exclude")
        pt = get_active_plan(self.user).plan_topics.get(topic=included)
        self.assertFalse(pt.included)
        self.assertEqual(pt.reason_code, "user_excluded")

        self.client.post(f"/ayarlar/konu/{included.pk}/", {"override": "force_include"})
        self.assertTrue(get_active_plan(self.user).plan_topics.get(topic=included).included)

        self.client.post(f"/ayarlar/konu/{included.pk}/", {"override": "auto"})
        row.refresh_from_db()
        self.assertIsNone(row.user_override)

    def test_topic_override_rejects_bad_requests(self):
        topic = Topic.objects.filter(subject__test__tracks=self.profile.track).first()
        self.assertEqual(self.client.get(f"/ayarlar/konu/{topic.pk}/").status_code, 405)
        self.assertEqual(self.client.post(f"/ayarlar/konu/{topic.pk}/", {"override": "evil"}).status_code, 404)
        foreign = Topic.objects.filter(subject__test__slug="ayt-fen").first()
        soz = make_onboarded_user("soz@example.com", track="SOZ")[0]
        self.client.force_login(soz)
        self.assertEqual(self.client.post(f"/ayarlar/konu/{foreign.pk}/", {"override": "force_include"}).status_code, 404)

    def test_override_only_redirects_to_safe_next(self):
        topic = Topic.objects.filter(subject__test__tracks=self.profile.track).first()
        ok = self.client.post(f"/ayarlar/konu/{topic.pk}/", {"override": "force_exclude", "next": "/plan/"})
        self.assertEqual(ok["Location"], "/plan/")
        evil = self.client.post(f"/ayarlar/konu/{topic.pk}/", {"override": "force_include", "next": "https://evil.example/"})
        self.assertTrue(evil["Location"].startswith("/ayarlar/konular/"))

    def test_topics_page_and_roadmap_offer_add_buttons(self):
        plan = get_active_plan(self.user)
        dropped = plan.plan_topics.filter(included=False, reason_code__in=["no_time", "big_topic_late"])
        self.assertTrue(dropped.exists())
        self.assertContains(self.client.get("/ayarlar/konular/"), "Yine de ekle")
        self.assertContains(self.client.get("/plan/"), "Bu konuyu yine de ekle")


class AccountDeletionTests(FrozenTodayMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def setUp(self):
        super().setUp()
        self.user, self.profile = make_onboarded_user(weekday=180, weekend=300)
        self.other, _ = make_onboarded_user("baska@example.com")
        add_mock(self.user)
        self.client.force_login(self.user)

    def test_wrong_password_deletes_nothing(self):
        response = self.client.post("/ayarlar/hesap-sil/", {"password": "yanlis-parola"})
        self.assertContains(response, "Parola hatalı")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_correct_password_deletes_account_and_all_data(self):
        pk = self.user.pk
        response = self.client.post("/ayarlar/hesap-sil/", {"password": PASSWORD})
        self.assertRedirects(response, "/")
        self.assertFalse(User.objects.filter(pk=pk).exists())
        for model in (StudentProfile, TopicProgress, Plan, Task, MockExam):
            self.assertFalse(model.objects.filter(user_id=pk).exists(), model.__name__)
        self.assertFalse(MockScore.objects.filter(mock__user_id=pk).exists())
        self.assertEqual(self.client.get("/bugun/").status_code, 302)  # logged out

    def test_other_users_data_is_untouched(self):
        self.client.post("/ayarlar/hesap-sil/", {"password": PASSWORD})
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())
        self.assertTrue(Task.objects.filter(user=self.other).exists())
        self.assertTrue(TopicProgress.objects.filter(user=self.other).exists())

    def test_get_only_shows_the_form_and_needs_login(self):
        self.assertContains(self.client.get("/ayarlar/hesap-sil/"), "kalıcı olarak silinir")
        self.client.logout()
        self.assertEqual(self.client.get("/ayarlar/hesap-sil/").status_code, 302)

    def test_a_user_who_has_not_finished_onboarding_can_still_delete(self):
        newcomer = make_user("yeni@example.com", "Yeni")
        self.client.force_login(newcomer)
        self.assertEqual(self.client.get("/ayarlar/hesap-sil/").status_code, 200)
        self.client.post("/ayarlar/hesap-sil/", {"password": PASSWORD})
        self.assertFalse(User.objects.filter(pk=newcomer.pk).exists())

    def test_password_guessing_is_rate_limited(self):
        for _ in range(10):
            self.client.post("/ayarlar/hesap-sil/", {"password": "yanlis"})
        response = self.client.post("/ayarlar/hesap-sil/", {"password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())


class TodayQueryCountTests(FrozenTodayMixin, TestCase):
    """/bugun/ must not run more queries when there are more tasks, topics or days."""

    @classmethod
    def setUpTestData(cls):
        seed_catalog()

    def count(self, user):
        self.client.force_login(user)
        self.client.get("/bugun/")  # the first visit of the day does the daily housekeeping
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/bugun/")
        self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_steady_state_query_count_does_not_depend_on_task_count(self):
        small, _ = make_onboarded_user("kucuk@example.com", weekday=90, weekend=120)
        big, _ = make_onboarded_user("buyuk@example.com", weekday=600, weekend=660)
        self.assertGreater(Task.objects.filter(user=big, date=D0).count(), Task.objects.filter(user=small, date=D0).count())
        counts = {self.count(small), self.count(big)}
        self.assertEqual(len(counts), 1, counts)
        self.assertLessEqual(counts.pop(), 20)

    def test_adding_many_tasks_adds_no_queries(self):
        user, _ = make_onboarded_user("elif@example.com")
        before = self.count(user)
        template = Task.objects.filter(user=user, date=D0).first()
        Task.objects.bulk_create(
            Task(user=user, plan=template.plan, date=D0, kind=template.kind, topic=template.topic, subject=template.subject,
                 title=template.title, minutes=20, order=50 + i)
            for i in range(25)
        )
        self.assertEqual(self.count(user), before)

    def test_first_visit_of_the_day_is_also_constant(self):
        small, _ = make_onboarded_user("kucuk@example.com", weekday=90, weekend=120)
        big, _ = make_onboarded_user("buyuk@example.com", weekday=600, weekend=660)
        results = []
        for user in (small, big):
            self.client.force_login(user)
            with CaptureQueriesContext(connection) as queries:
                self.client.get("/bugun/")
            results.append(len(queries))
        self.assertEqual(results[0], results[1], results)
