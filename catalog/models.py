from django.db import models


class Exam(models.Model):
    slug = models.SlugField("kısa ad", unique=True)
    name = models.CharField("ad", max_length=100)
    is_active = models.BooleanField("kayıtta seçilebilir", default=True)

    class Meta:
        verbose_name = "sınav"
        verbose_name_plural = "sınavlar"

    def __str__(self):
        return self.name


class ExamSession(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="sessions", verbose_name="sınav")
    code = models.CharField("kod", max_length=10)
    name = models.CharField("ad", max_length=100)
    date = models.DateField("tarih")
    date_is_estimated = models.BooleanField("tarih tahmini", default=True)
    duration_minutes = models.PositiveIntegerField("süre (dk)")
    order = models.PositiveSmallIntegerField("sıra", default=0)

    class Meta:
        ordering = ["exam", "order"]
        constraints = [models.UniqueConstraint(fields=["exam", "code"], name="catalog_session_exam_code_unique")]
        verbose_name = "oturum"
        verbose_name_plural = "oturumlar"

    def __str__(self):
        return f"{self.exam.name} – {self.code}"


class ExamTest(models.Model):
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name="tests", verbose_name="oturum")
    slug = models.SlugField("kısa ad", unique=True)
    name = models.CharField("ad", max_length=150)
    question_count = models.PositiveSmallIntegerField("soru sayısı")
    order = models.PositiveSmallIntegerField("sıra", default=0)

    class Meta:
        ordering = ["session", "order"]
        verbose_name = "test"
        verbose_name_plural = "testler"

    def __str__(self):
        return f"{self.session.code} {self.name}"


class Subject(models.Model):
    class Group(models.TextChoices):
        QUANT = "quant", "Sayısal"
        VERBAL = "verbal", "Sözel"
        SCIENCE = "science", "Fen"
        SOCIAL = "social", "Sosyal"
        LANGUAGE = "language", "Dil"

    test = models.ForeignKey(ExamTest, on_delete=models.CASCADE, related_name="subjects", verbose_name="test")
    slug = models.SlugField("kısa ad", unique=True)
    name = models.CharField("ad", max_length=100)
    question_count = models.PositiveSmallIntegerField("soru sayısı")
    question_count_is_estimated = models.BooleanField("soru sayısı tahmini", default=False)
    minutes_per_question = models.DecimalField("soru başına dakika (tahmini)", max_digits=4, decimal_places=1)
    group = models.CharField("grup", max_length=10, choices=Group.choices)
    color = models.CharField("renk (hex)", max_length=7)
    order = models.PositiveSmallIntegerField("sıra", default=0)

    class Meta:
        ordering = ["test", "order"]
        verbose_name = "ders"
        verbose_name_plural = "dersler"

    def __str__(self):
        return f"{self.test.session.code} {self.name}"


class Topic(models.Model):
    class Difficulty(models.IntegerChoices):
        EASY = 1, "Kolay"
        MEDIUM = 2, "Orta"
        HARD = 3, "Zor"

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="topics", verbose_name="ders")
    slug = models.SlugField("kısa ad", unique=True, max_length=80)
    name = models.CharField("ad", max_length=150)
    order = models.PositiveSmallIntegerField("müfredat sırası", default=0)
    avg_questions = models.DecimalField("ortalama soru sayısı", max_digits=4, decimal_places=2)
    learn_hours = models.DecimalField("öğrenme süresi (saat)", max_digits=5, decimal_places=1)
    difficulty = models.PositiveSmallIntegerField("zorluk", choices=Difficulty.choices, default=Difficulty.MEDIUM)
    is_estimated = models.BooleanField("değerler tahmini", default=True)
    source_note = models.TextField("kaynak notu", blank=True)
    prerequisites = models.ManyToManyField(
        "self", symmetrical=False, related_name="unlocks", blank=True, verbose_name="ön koşullar"
    )
    is_active = models.BooleanField("aktif", default=True)

    class Meta:
        ordering = ["subject", "order"]
        verbose_name = "konu"
        verbose_name_plural = "konular"

    def __str__(self):
        return f"{self.subject.name} – {self.name}"

    @property
    def efficiency(self):
        """Questions gained per learning hour (computed, never stored)."""
        return self.avg_questions / self.learn_hours if self.learn_hours else None


class Track(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="tracks", verbose_name="sınav")
    code = models.CharField("kod", max_length=10)
    name = models.CharField("ad", max_length=50)
    tests = models.ManyToManyField(ExamTest, related_name="tracks", verbose_name="plana dahil testler")

    class Meta:
        ordering = ["exam", "id"]
        constraints = [models.UniqueConstraint(fields=["exam", "code"], name="catalog_track_exam_code_unique")]
        verbose_name = "alan"
        verbose_name_plural = "alanlar"

    def __str__(self):
        return f"{self.exam.name} – {self.name}"
