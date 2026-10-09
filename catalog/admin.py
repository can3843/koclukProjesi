from decimal import Decimal

from django import forms
from django.contrib import admin
from django.db.models import Count, Sum
from django.utils.html import format_html

from .models import Exam, ExamSession, ExamTest, Subject, Topic, Track
from .validation import QUESTION_TOLERANCE, find_cycle


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ("exam", "code", "name", "date", "date_is_estimated", "duration_minutes", "order")
    list_filter = ("exam", "date_is_estimated")


@admin.register(ExamTest)
class ExamTestAdmin(admin.ModelAdmin):
    list_display = ("name", "session", "question_count", "order")
    list_filter = ("session",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = (
        "name", "test", "question_count", "question_count_is_estimated",
        "topic_count", "topic_question_total", "group", "color", "order",
    )
    list_filter = ("test__session", "test", "group", "question_count_is_estimated")
    search_fields = ("name", "slug")
    list_select_related = ("test__session",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_topic_count=Count("topics"), _topic_total=Sum("topics__avg_questions"))

    @admin.display(description="konu sayısı", ordering="_topic_count")
    def topic_count(self, obj):
        return obj._topic_count

    @admin.display(description="konu soru toplamı", ordering="_topic_total")
    def topic_question_total(self, obj):
        total = obj._topic_total or Decimal("0")
        if abs(total - obj.question_count) > QUESTION_TOLERANCE:
            return format_html('<strong style="color:#E5484D">{} ≠ {}</strong>', total, obj.question_count)
        return total


class TopicAdminForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = "__all__"

    def clean_prerequisites(self):
        prerequisites = self.cleaned_data["prerequisites"]
        subject = self.cleaned_data.get("subject")
        if self.instance.pk and prerequisites.filter(pk=self.instance.pk).exists():
            raise forms.ValidationError("Bir konu kendi kendisinin ön koşulu olamaz.")
        if subject is not None:
            exam_id = subject.test.session.exam_id
            if any(p.subject.test.session.exam_id != exam_id for p in prerequisites):
                raise forms.ValidationError("Ön koşullar aynı sınavın konuları olmalı.")
        if self.instance.pk:
            graph = {t.pk: [p.pk for p in t.prerequisites.all()] for t in Topic.objects.prefetch_related("prerequisites")}
            graph[self.instance.pk] = [p.pk for p in prerequisites]
            if find_cycle(graph):
                raise forms.ValidationError("Bu seçim ön koşullarda döngü oluşturuyor.")
        return prerequisites


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    form = TopicAdminForm
    list_display = ("name", "subject", "avg_questions", "learn_hours", "difficulty", "is_estimated", "efficiency_display", "is_active")
    list_editable = ("avg_questions", "learn_hours", "difficulty", "is_estimated")
    list_filter = ("subject__test__session", "subject", "is_estimated", "difficulty", "is_active")
    search_fields = ("name", "slug", "subject__name")
    list_select_related = ("subject__test__session",)
    filter_horizontal = ("prerequisites",)
    list_per_page = 100

    @admin.display(description="verimlilik (soru/saat)")
    def efficiency_display(self, obj):
        value = obj.efficiency
        return f"{value:.2f}" if value is not None else "—"


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "exam")
    filter_horizontal = ("tests",)
