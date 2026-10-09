from django.core.management.base import BaseCommand, CommandError

from catalog.models import Exam
from catalog.validation import validate_catalog


class Command(BaseCommand):
    help = "Sınav verisini doğrular (soru toplamları, ön koşul döngüleri vb.)."

    def add_arguments(self, parser):
        parser.add_argument("--exam", help="Yalnızca bu sınavı (slug) kontrol et.")

    def handle(self, *args, **options):
        exam = None
        if options["exam"]:
            try:
                exam = Exam.objects.get(slug=options["exam"])
            except Exam.DoesNotExist:
                raise CommandError(f"Sınav bulunamadı: {options['exam']}")

        report = validate_catalog(exam)

        for message in report.errors:
            self.stdout.write(self.style.ERROR(f"HATA: {message}"))
        for message in report.warnings:
            self.stdout.write(self.style.WARNING(f"UYARI: {message}"))
        self.stdout.write(
            f"{report.total_topics} konu kontrol edildi; {report.estimated_topics} tanesi tahmini işaretli. "
            f"{len(report.errors)} hata, {len(report.warnings)} uyarı."
        )
        if report.errors:
            raise CommandError("Sınav verisinde hata var.")
        self.stdout.write(self.style.SUCCESS("Sınav verisi geçerli."))
