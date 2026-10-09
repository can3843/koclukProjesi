from django.contrib import admin

from .models import MockExam, MockScore, Plan, PlanTopic, StudentProfile, TopicProgress


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "track", "weekday_minutes", "weekend_minutes", "onboarding_step", "onboarding_completed_at")
    list_select_related = ("user", "track")
    search_fields = ("user__email",)


class PlanTopicInline(admin.TabularInline):
    model = PlanTopic
    extra = 0
    can_delete = False
    raw_id_fields = ("topic",)
    readonly_fields = ("topic", "included", "sequence", "priority", "gain", "need_minutes", "reason_code", "start_day")


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "phase_code", "days_left", "coverage_ratio", "reason", "is_active", "created_at")
    list_filter = ("phase_code", "reason", "is_active")
    search_fields = ("user__email",)
    inlines = [PlanTopicInline]


class MockScoreInline(admin.TabularInline):
    model = MockScore
    extra = 0


@admin.register(MockExam)
class MockExamAdmin(admin.ModelAdmin):
    list_display = ("user", "session", "taken_on")
    inlines = [MockScoreInline]


@admin.register(TopicProgress)
class TopicProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "topic", "level", "state", "boost")
    list_filter = ("level", "state")
    raw_id_fields = ("user", "topic")
