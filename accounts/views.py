from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from .forms import EmailAuthenticationForm, RegisterForm


def register(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Hoş geldin {user.first_name}! 👋")
        # Phase 3 will send new users to onboarding instead.
        return redirect(settings.LOGIN_REDIRECT_URL)
    return render(request, "accounts/register.html", {"form": form})


class RotamLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True
