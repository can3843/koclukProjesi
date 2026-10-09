from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render

from . import ratelimit
from .forms import EmailAuthenticationForm, RegisterForm

TOO_MANY = "Çok fazla deneme yaptın. Biraz bekleyip tekrar dene."


def register(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    if request.method == "POST":
        if ratelimit.is_limited("register", request, ratelimit.REGISTER_ATTEMPTS):
            return render(request, "accounts/register.html", {"form": RegisterForm(), "rate_limited": TOO_MANY}, status=429)
        ratelimit.record("register", request, ratelimit.REGISTER_ATTEMPTS)

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Hoş geldin {user.first_name}! 👋")
        # The onboarding middleware sends new users to their onboarding step.
        return redirect(settings.LOGIN_REDIRECT_URL)
    return render(request, "accounts/register.html", {"form": form})


class RotamLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        if ratelimit.is_limited("login", request, ratelimit.LOGIN_FAILURES):
            form = self.get_form_class()(request=request)  # unbound: the credentials are not even checked
            return self.render_to_response(self.get_context_data(form=form, rate_limited=TOO_MANY), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        ratelimit.record("login", self.request, ratelimit.LOGIN_FAILURES)
        return super().form_invalid(form)

    def form_valid(self, form):
        ratelimit.reset("login", self.request)
        return super().form_valid(form)
