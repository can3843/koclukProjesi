import json
from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .models import Exam, ExamSession, ExamTest, Subject, Topic, Track
from .validation import find_cycle, validate_catalog

DATA_FILE = Path(settings.BASE_DIR) / "data" / "yks_2027.json"


def make_catalog():
    """Tiny artificial catalog: one test of 10 questions with two subjects (6 + 4)."""
    exam = Exam.objects.create(slug="mini", name="Mini Sınav")
    session = ExamSession.objects.create(
        exam=exam, code="MS", name="Mini Oturum", date="2027-06-19", duration_minutes=60, order=1
    )
    test = ExamTest.objects.create(session=session, slug="mini-test", name="Mini Test", question_count=10, order=1)
    math = Subject.objects.create(
        test=test, slug="mini-mat", name="Mat", question_count=6, minutes_per_question=Decimal("2.0"),
        group="quant", color="#5B5BD6", order=1,
    )
    phys = Subject.objects.create(
        test=test, slug="mini-fiz", name="Fiz", question_count=4, minutes_per_question=Decimal("2.0"),
        group="science", color="#14A3C7", order=2,
    )
    topics = {}
    for slug, subject, avg in [("a", math, "3"), ("b", math, "3"), ("c", phys, "4")]:
        topics[slug] = Topic.objects.create(
            subject=subject, slug=f"mini-{slug}", name=slug.upper(), order=1,
            avg_questions=Decimal(avg), learn_hours=Decimal("5"),
        )
    return exam, test, topics


class FindCycleTests(TestCase):
    def test_no_cycle(self):
        self.assertIsNone(find_cycle({"a": ["b"], "b": ["c"], "c": []}))

    def test_cycle_is_found(self):
        cycle = find_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"a", "b", "c"})

    def test_self_loop_is_a_cycle(self):
        self.assertIsNotNone(find_cycle({"a": ["a"]}))


class ValidationTests(TestCase):
    def test_valid_catalog_has_no_errors_or_warnings(self):
        exam, _, _ = make_catalog()
        report = validate_catalog(exam)
        self.assertTrue(report.ok)
        self.assertEqual(report.warnings, [])
        self.assertEqual(report.total_topics, 3)

    def test_subject_topic_total_mismatch_is_a_warning(self):
        exam, _, topics = make_catalog()
        topics["a"].avg_questions = Decimal("1")
        topics["a"].save()
        report = validate_catalog(exam)
        self.assertTrue(report.ok)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("mini-mat", report.warnings[0])

    def test_subject_total_within_tolerance_is_ok(self):
        exam, _, topics = make_catalog()
        topics["a"].avg_questions = Decimal("3.4")
        topics["a"].save()
        self.assertEqual(validate_catalog(exam).warnings, [])

    def test_test_total_mismatch_is_an_error(self):
        exam, test, _ = make_catalog()
        test.question_count = 12
        test.save()
        report = validate_catalog(exam)
        self.assertFalse(report.ok)
        self.assertIn("mini-test", report.errors[0])

    def test_self_prerequisite_is_an_error(self):
        exam, _, topics = make_catalog()
        topics["a"].prerequisites.add(topics["a"])
        report = validate_catalog(exam)
        self.assertFalse(report.ok)
        self.assertTrue(any("kendi kendisinin" in e for e in report.errors))

    def test_prerequisite_cycle_is_an_error(self):
        exam, _, topics = make_catalog()
        topics["a"].prerequisites.add(topics["b"])
        topics["b"].prerequisites.add(topics["c"])
        topics["c"].prerequisites.add(topics["a"])
        report = validate_catalog(exam)
        self.assertFalse(report.ok)
        self.assertTrue(any("döngü" in e for e in report.errors))

    def test_prerequisite_from_other_exam_is_an_error(self):
        exam, _, topics = make_catalog()
        other = Exam.objects.create(slug="diger", name="Diğer")
        session = ExamSession.objects.create(
            exam=other, code="D", name="D", date="2027-06-19", duration_minutes=60, order=1
        )
        test = ExamTest.objects.create(session=session, slug="d-test", name="D", question_count=1, order=1)
        subject = Subject.objects.create(
            test=test, slug="d-s", name="D", question_count=1, minutes_per_question=Decimal("1.0"),
            group="quant", color="#000000", order=1,
        )
        foreign = Topic.objects.create(
            subject=subject, slug="d-t", name="D", order=1, avg_questions=Decimal("1"), learn_hours=Decimal("1")
        )
        topics["a"].prerequisites.add(foreign)
        report = validate_catalog(exam)
        self.assertTrue(any("başka bir sınava" in e for e in report.errors))

    def test_non_positive_learn_hours_is_an_error(self):
        exam, _, topics = make_catalog()
        topics["a"].learn_hours = Decimal("0")
        topics["a"].save()
        self.assertFalse(validate_catalog(exam).ok)

    def test_estimated_topics_are_counted(self):
        exam, _, topics = make_catalog()
        topics["a"].is_estimated = False
        topics["a"].save()
        self.assertEqual(validate_catalog(exam).estimated_topics, 2)

    def test_check_command_fails_on_errors(self):
        _, test, _ = make_catalog()
        test.question_count = 12
        test.save()
        with self.assertRaises(CommandError):
            call_command("check_exam_data", stdout=StringIO())


class SeedTests(TestCase):
    def seed(self, path=DATA_FILE):
        call_command("seed_exam_data", str(path), stdout=StringIO())

    def counts(self):
        return {
            "exams": Exam.objects.count(),
            "sessions": ExamSession.objects.count(),
            "tests": ExamTest.objects.count(),
            "subjects": Subject.objects.count(),
            "topics": Topic.objects.count(),
            "tracks": Track.objects.count(),
            "prereqs": Topic.prerequisites.through.objects.count(),
        }

    def test_seed_twice_creates_no_duplicates(self):
        self.seed()
        first = self.counts()
        self.seed()
        self.assertEqual(self.counts(), first)

    def test_seed_loads_expected_structure(self):
        self.seed()
        counts = self.counts()
        self.assertEqual(counts["exams"], 1)
        self.assertEqual(counts["sessions"], 3)
        self.assertEqual(counts["tracks"], 4)
        self.assertGreater(counts["topics"], 200)
        say = Track.objects.get(code="SAY")
        self.assertEqual(say.tests.count(), 6)
        self.assertEqual(Track.objects.get(code="DIL").tests.filter(slug="ydt-yabanci-dil").count(), 1)

    def test_shipped_data_passes_validation(self):
        self.seed()
        report = validate_catalog()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.warnings, [])
        # every value in the shipped file is estimated until verified (CLAUDE.md §0 rule 5)
        self.assertEqual(report.estimated_topics, report.total_topics)

    def test_session_dates_are_marked_estimated(self):
        self.seed()
        self.assertFalse(ExamSession.objects.filter(date_is_estimated=False).exists())

    def test_seed_updates_existing_rows_by_slug(self):
        self.seed()
        topic = Topic.objects.get(slug="tyt-matematik-uslu-sayilar")
        topic.learn_hours = Decimal("99")
        topic.save()
        self.seed()
        topic.refresh_from_db()
        self.assertNotEqual(topic.learn_hours, Decimal("99"))

    def test_seed_does_not_touch_user_data(self):
        user = get_user_model().objects.create_user("elif@example.com", "gizli-parola-123", first_name="Elif")
        self.seed()
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())

    def test_invalid_data_aborts_without_saving(self):
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        data["tests"][0]["question_count"] += 5
        bad = Path(settings.BASE_DIR) / "data" / "_bad_test_file.json"
        bad.write_text(json.dumps(data), encoding="utf-8")
        try:
            with self.assertRaises(CommandError):
                self.seed(bad)
        finally:
            bad.unlink()
        self.assertEqual(Topic.objects.count(), 0)

    def test_prerequisites_are_loaded(self):
        self.seed()
        kokluler = Topic.objects.get(slug="tyt-matematik-koklu-sayilar")
        self.assertEqual([t.slug for t in kokluler.prerequisites.all()], ["tyt-matematik-uslu-sayilar"])


class AdminTests(TestCase):
    def setUp(self):
        call_command("seed_exam_data", str(DATA_FILE), stdout=StringIO())
        admin = get_user_model().objects.create_superuser("admin@example.com", "gizli-parola-123", first_name="Admin")
        self.client.force_login(admin)

    def test_changelists_render(self):
        for model in ("exam", "examsession", "examtest", "subject", "topic", "track"):
            response = self.client.get(f"/yonetim/catalog/{model}/")
            self.assertEqual(response.status_code, 200, model)

    def test_subject_list_shows_topic_counts(self):
        response = self.client.get("/yonetim/catalog/subject/")
        self.assertContains(response, "Konu sayısı")

    def test_topic_change_form_renders(self):
        topic = Topic.objects.get(slug="tyt-matematik-koklu-sayilar")
        response = self.client.get(f"/yonetim/catalog/topic/{topic.pk}/change/")
        self.assertEqual(response.status_code, 200)

    def test_admin_rejects_self_prerequisite(self):
        topic = Topic.objects.get(slug="tyt-matematik-koklu-sayilar")
        response = self.client.post(
            f"/yonetim/catalog/topic/{topic.pk}/change/",
            {
                "subject": topic.subject_id, "slug": topic.slug, "name": topic.name, "order": topic.order,
                "avg_questions": topic.avg_questions, "learn_hours": topic.learn_hours,
                "difficulty": topic.difficulty, "is_estimated": "on", "source_note": "", "is_active": "on",
                "prerequisites": [topic.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kendi kendisinin ön koşulu")
