from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class RegisterForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Parola",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Parola (tekrar)",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = ("first_name", "email")
        labels = {"first_name": "Adın", "email": "E-posta"}
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name", "autofocus": True}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    field_order = ("first_name", "email", "password1", "password2")

    def clean_first_name(self):
        name = self.cleaned_data["first_name"].strip()
        if not 2 <= len(name) <= 30:
            raise ValidationError("Adın 2 ile 30 karakter arasında olmalı.")
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Bu e-posta ile zaten bir hesap var. Giriş yapmayı dene.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Parolalar eşleşmiyor.")
        elif password1:
            candidate = User(first_name=cleaned.get("first_name", ""), email=cleaned.get("email", ""))
            try:
                validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="E-posta",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )
    password = forms.CharField(
        label="Parola",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    error_messages = {
        "invalid_login": "E-posta veya parola hatalı.",
        "inactive": "Bu hesap aktif değil.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
