from django.conf import settings
from django.shortcuts import redirect, render


def home(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    return render(request, "home.html")
