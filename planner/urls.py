from django.urls import path

from .views import onboarding, plan, today

urlpatterns = [
    path("baslangic/<int:step>/", onboarding.onboarding_step, name="onboarding_step"),
    path("plan/", plan.plan_roadmap, name="plan_roadmap"),
    path("plan/rapor/", plan.plan_report, name="plan_report"),
    path("bugun/", today.today_view, name="today"),
    path("hafta/", today.week_view, name="week"),
    path("gorev/<int:pk>/tamamla/", today.task_action, {"action": "complete"}, name="task_complete"),
    path("gorev/<int:pk>/atla/", today.task_action, {"action": "skip"}, name="task_skip"),
    path("gorev/<int:pk>/geri-al/", today.task_action, {"action": "undo"}, name="task_undo"),
]
