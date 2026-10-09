from django.shortcuts import redirect

from .models import StudentProfile

# Pages a user may open before finishing onboarding.
EXEMPT_PREFIXES = ("/baslangic/", "/cikis/", "/yonetim/", "/static/", "/giris/", "/kayit/", "/ayarlar/hesap-sil/")


class OnboardingMiddleware:
    """Attach the student's profile and send users who have not finished onboarding to their current step."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.student_profile = None
        user = request.user
        if user.is_authenticated and not request.path.startswith("/static/"):
            profile = StudentProfile.objects.select_related("exam", "track").filter(user=user).first()
            request.student_profile = profile
            exempt = request.path.startswith(EXEMPT_PREFIXES)
            if not exempt and (profile is None or not profile.is_onboarded):
                step = profile.onboarding_step if profile else 1
                return redirect("onboarding_step", step=step)
        return self.get_response(request)
