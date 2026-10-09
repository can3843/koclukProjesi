from django.urls import path

from .views import onboarding, plan

urlpatterns = [
    path("baslangic/<int:step>/", onboarding.onboarding_step, name="onboarding_step"),
    path("plan/", plan.plan_roadmap, name="plan_roadmap"),
    path("plan/rapor/", plan.plan_report, name="plan_report"),
]
