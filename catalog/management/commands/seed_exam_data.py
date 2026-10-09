import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Exam, ExamSession, ExamTest, Subject, Topic, Track
from catalog.validation import validate_catalog


def dec(value):
    return Decimal(str(value))


class Command(BaseCommand):
    help = "Sınav verisini JSON dosyasından slug'a göre ekler/günceller (tekrar çalıştırılabilir)."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Örn. data/yks_2027.json")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"Dosya bulunamadı: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise CommandError(f"JSON okunamadı: {error}")

        try:
            with transaction.atomic():
                exam = self.upsert(data)
                report = validate_catalog(exam)
                if report.errors:
                    for message in report.errors:
                        self.stdout.write(self.style.ERROR(f"HATA: {message}"))
                    raise CommandError("Veri doğrulamadan geçmedi; hiçbir değişiklik kaydedilmedi.")
        except KeyError as error:
            raise CommandError(f"JSON'da eksik ya da hatalı başvuru: {error}")

        for message in report.warnings:
            self.stdout.write(self.style.WARNING(f"UYARI: {message}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"'{exam.name}' yüklendi: {report.total_topics} konu "
                f"({report.estimated_topics} tanesi tahmini), {len(report.warnings)} uyarı."
            )
        )

    def upsert(self, data):
        exam_data = data["exam"]
        exam, _ = Exam.objects.update_or_create(
            slug=exam_data["slug"], defaults={"name": exam_data["name"], "is_active": exam_data.get("is_active", True)}
        )

        sessions = {}
        for item in data["sessions"]:
            sessions[item["code"]], _ = ExamSession.objects.update_or_create(
                exam=exam,
                code=item["code"],
                defaults={
                    "name": item["name"],
                    "date": item["date"],
                    "date_is_estimated": item["date_is_estimated"],
                    "duration_minutes": item["duration_minutes"],
                    "order": item["order"],
                },
            )

        tests = {}
        for item in data["tests"]:
            tests[item["slug"]], _ = ExamTest.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "session": sessions[item["session"]],
                    "name": item["name"],
                    "question_count": item["question_count"],
                    "order": item["order"],
                },
            )

        subjects = {}
        for item in data["subjects"]:
            subjects[item["slug"]], _ = Subject.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "test": tests[item["test"]],
                    "name": item["name"],
                    "question_count": item["question_count"],
                    "question_count_is_estimated": item.get("question_count_is_estimated", False),
                    "minutes_per_question": dec(item["minutes_per_question"]),
                    "group": item["group"],
                    "color": item["color"],
                    "order": item["order"],
                },
            )

        topics = {}
        for item in data["topics"]:
            topics[item["slug"]], _ = Topic.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "subject": subjects[item["subject"]],
                    "name": item["name"],
                    "order": item["order"],
                    "avg_questions": dec(item["avg_questions"]),
                    "learn_hours": dec(item["learn_hours"]),
                    "difficulty": item["difficulty"],
                    "is_estimated": item.get("is_estimated", True),
                    "source_note": item.get("source_note", ""),
                    "is_active": item.get("is_active", True),
                },
            )
        for item in data["topics"]:
            topics[item["slug"]].prerequisites.set([topics[slug] for slug in item.get("prerequisites", [])])

        for item in data["tracks"]:
            track, _ = Track.objects.update_or_create(
                exam=exam, code=item["code"], defaults={"name": item["name"]}
            )
            track.tests.set([tests[slug] for slug in item["tests"]])

        return exam
