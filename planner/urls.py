from django.urls import path

from .views import mocks, onboarding, plan, progress, review, settings, today

urlpatterns = [
    path("baslangic/<int:step>/", onboarding.onboarding_step, name="onboarding_step"),
    path("plan/", plan.plan_roadmap, name="plan_roadmap"),
    path("plan/rapor/", plan.plan_report, name="plan_report"),
    path("bugun/", today.today_view, name="today"),
    path("hafta/", today.week_view, name="week"),
    path("gorev/<int:pk>/tamamla/", today.task_action, {"action": "complete"}, name="task_complete"),
    path("gorev/<int:pk>/atla/", today.task_action, {"action": "skip"}, name="task_skip"),
    path("gorev/<int:pk>/geri-al/", today.task_action, {"action": "undo"}, name="task_undo"),
    path("gorev/<int:pk>/sure/", today.task_focus, name="task_focus"),
    path("deneme/", mocks.mock_list, name="mock_list"),
    path("deneme/ekle/", mocks.mock_add, name="mock_add"),
    path("deneme/<int:pk>/", mocks.mock_detail, name="mock_detail"),
    path("deneme/<int:pk>/konu-ekle/<int:topic_id>/", mocks.mock_add_topic, name="mock_add_topic"),
    path("plan/kapsam-onerisi/", review.rescope, name="rescope"),
    path("degerlendirme/", review.weekly_reviews, name="weekly_reviews"),
    path("ilerleme/", progress.progress_view, name="progress"),
    path("ayarlar/", settings.settings_home, name="settings"),
    path("ayarlar/seviyeler/", settings.settings_levels, name="settings_levels"),
    path("ayarlar/konular/", settings.settings_topics, name="settings_topics"),
    path("ayarlar/konu/<int:topic_id>/", settings.topic_override, name="topic_override"),
    path("ayarlar/hesap-sil/", settings.account_delete, name="account_delete"),
]
