from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


def validate_half_hour(value):
    if value % 30:
        raise ValidationError("Süre 30 dakikanın katı olmalı.")


class StudentProfile(models.Model):
    class PeakTime(models.TextChoices):
        MORNING = "morning", "Sabah"
        NOON = "noon", "Öğle"
        EVENING = "evening", "Akşam"
        NIGHT = "night", "Gece"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
    exam = models.ForeignKey("catalog.Exam", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    track = models.ForeignKey("catalog.Track", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    weekday_minutes = models.PositiveSmallIntegerField(
        "hafta içi günlük dakika", default=120,
        validators=[MinValueValidator(30), MaxValueValidator(600), validate_half_hour],
    )
    weekend_minutes = models.PositiveSmallIntegerField(
        "hafta sonu günlük dakika", default=240,
        validators=[MinValueValidator(30), MaxValueValidator(660), validate_half_hour],
    )
    rest_weekday = models.PositiveSmallIntegerField(
        "dinlenme günü (0=pazartesi)", null=True, blank=True, validators=[MaxValueValidator(6)]
    )
    peak_time = models.CharField("verimli saat", max_length=10, choices=PeakTime.choices, default=PeakTime.MORNING)
    target_department = models.CharField("hedef bölüm", max_length=100, blank=True)
    target_tyt_net = models.DecimalField("hedef TYT neti", max_digits=5, decimal_places=2, null=True, blank=True)
    target_ayt_net = models.DecimalField("hedef AYT/YDT neti", max_digits=5, decimal_places=2, null=True, blank=True)
    onboarding_step = models.PositiveSmallIntegerField(
        "tanışma adımı", default=1, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    last_daily_sync = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "öğrenci profili"
        verbose_name_plural = "öğrenci profilleri"

    def __str__(self):
        return f"Profil: {self.user}"

    @property
    def is_onboarded(self):
        return self.onboarding_completed_at is not None


class TopicProgress(models.Model):
    class Level(models.IntegerChoices):
        NONE = 0, "Hiç bilmiyorum"
        SOME = 1, "Biraz biliyorum"
        GOOD = 2, "İyiyim"

    class State(models.TextChoices):
        NOT_STARTED = "not_started", "Başlanmadı"
        IN_PROGRESS = "in_progress", "Devam ediyor"
        LEARNED = "learned", "Öğrenildi"
        EXCLUDED = "excluded", "Kapsam dışı"

    class Override(models.TextChoices):
        FORCE_INCLUDE = "force_include", "Yine de ekle"
        FORCE_EXCLUDE = "force_exclude", "Çıkar"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="topic_progress")
    topic = models.ForeignKey("catalog.Topic", on_delete=models.CASCADE, related_name="+")
    initial_level = models.PositiveSmallIntegerField(choices=Level.choices, default=Level.NONE)
    level = models.PositiveSmallIntegerField(choices=Level.choices, default=Level.NONE)
    state = models.CharField(max_length=12, choices=State.choices, default=State.NOT_STARTED)
    remaining_learn_minutes = models.PositiveIntegerField(null=True, blank=True)
    remaining_practice_minutes = models.PositiveIntegerField(null=True, blank=True)
    learned_on = models.DateField(null=True, blank=True)
    boost = models.FloatField(default=1.0, validators=[MinValueValidator(1.0), MaxValueValidator(2.0)])
    questions_solved = models.PositiveIntegerField(default=0)
    questions_correct = models.PositiveIntegerField(default=0)
    questions_wrong = models.PositiveIntegerField(default=0)
    user_override = models.CharField(max_length=14, choices=Override.choices, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "topic"], name="planner_progress_user_topic_unique")]
        verbose_name = "konu ilerlemesi"
        verbose_name_plural = "konu ilerlemeleri"

    def __str__(self):
        return f"{self.user} – {self.topic}"


class Plan(models.Model):
    class Reason(models.TextChoices):
        ONBOARDING = "onboarding", "Tanışma"
        PHASE_CHANGE = "phase_change", "Dönem değişimi"
        SETTINGS_CHANGE = "settings_change", "Ayar değişikliği"
        RESCOPE = "rescope", "Kapsam güncellemesi"
        LEVELS_CHANGED = "levels_changed", "Seviye değişikliği"
        MANUAL = "manual", "Elle"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plans")
    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=16, choices=Reason.choices)
    phase_code = models.CharField(max_length=2)
    days_left = models.IntegerField()
    budget = models.JSONField(default=dict)
    required_minutes = models.PositiveIntegerField(default=0)
    coverage_ratio = models.FloatField(default=0)
    projection = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(is_active=True), name="planner_one_active_plan_per_user"),
        ]
        verbose_name = "plan"
        verbose_name_plural = "planlar"

    def __str__(self):
        return f"Plan {self.pk} ({self.user}, {self.phase_code})"


class PlanTopic(models.Model):
    class ReasonCode(models.TextChoices):
        SELECTED = "selected", "Seçildi"
        ALREADY_GOOD = "already_good", "Zaten iyi"
        NO_TIME = "no_time", "Vakit yok"
        BIG_TOPIC_LATE = "big_topic_late", "Büyük konu, geç kalındı"
        USER_EXCLUDED = "user_excluded", "Kullanıcı çıkardı"
        PREREQUISITE = "prerequisite", "Ön koşul"

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_topics")
    topic = models.ForeignKey("catalog.Topic", on_delete=models.CASCADE, related_name="+")
    included = models.BooleanField()
    sequence = models.PositiveSmallIntegerField(null=True, blank=True)
    priority = models.FloatField(default=0)
    gain = models.FloatField(default=0)
    need_minutes = models.PositiveIntegerField(default=0)
    reason_code = models.CharField(max_length=16, choices=ReasonCode.choices)
    start_day = models.PositiveSmallIntegerField(null=True, blank=True)  # rough day offset for the roadmap

    class Meta:
        ordering = ["sequence", "id"]
        constraints = [models.UniqueConstraint(fields=["plan", "topic"], name="planner_plantopic_plan_topic_unique")]

    def __str__(self):
        return f"{self.plan_id}: {self.topic_id} ({self.reason_code})"


class MockExam(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mock_exams")
    session = models.ForeignKey("catalog.ExamSession", on_delete=models.PROTECT, related_name="+")
    taken_on = models.DateField("çözüldüğü tarih")
    weak_topics = models.ManyToManyField("catalog.Topic", blank=True, related_name="+")
    # `task` (link to a planned mock task) is added together with the Task model in Phase 4.

    class Meta:
        ordering = ["-taken_on", "-id"]
        verbose_name = "deneme"
        verbose_name_plural = "denemeler"

    def __str__(self):
        return f"{self.session.code} denemesi ({self.taken_on})"


class MockScore(models.Model):
    mock = models.ForeignKey(MockExam, on_delete=models.CASCADE, related_name="scores")
    subject = models.ForeignKey("catalog.Subject", on_delete=models.PROTECT, related_name="+")
    correct = models.PositiveSmallIntegerField(default=0)
    wrong = models.PositiveSmallIntegerField(default=0)
    blank = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["mock", "subject"], name="planner_mockscore_mock_subject_unique")]

    def clean(self):
        if self.subject_id and self.correct + self.wrong + self.blank > self.subject.question_count:
            raise ValidationError(f"{self.subject.name} için toplam {self.subject.question_count} soruyu geçemez.")

    @property
    def net(self):
        return Decimal(self.correct) - Decimal(self.wrong) / 4

    def __str__(self):
        return f"{self.mock} – {self.subject.name}"
