from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def home(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    return render(request, "home.html")


@login_required
def today(request):
    # Placeholder until the daily task screen (Phase 4).
    return render(request, "core/today_placeholder.html")
