from datetime import date
from decimal import Decimal

from django import forms
from django.utils import timezone

from .models import StudentProfile

WEEKDAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class TrackForm(forms.Form):
    track = forms.ChoiceField(label="Alan", widget=forms.RadioSelect)

    def __init__(self, *args, tracks=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["track"].choices = [(str(t.pk), t.name) for t in tracks]
        self.fields["track"].error_messages["required"] = "Lütfen bir alan seç."
        self.fields["track"].error_messages["invalid_choice"] = "Geçerli bir alan seç."


class TimeForm(forms.Form):
    weekday_minutes = forms.IntegerField(label="Hafta içi", min_value=30, max_value=600)
    weekend_minutes = forms.IntegerField(label="Hafta sonu", min_value=30, max_value=660)

    def _check_step(self, name):
        value = self.cleaned_data[name]
        if value % 30:
            raise forms.ValidationError("Süre 30 dakikanın katı olmalı.")
        return value

    def clean_weekday_minutes(self):
        return self._check_step("weekday_minutes")

    def clean_weekend_minutes(self):
        return self._check_step("weekend_minutes")


class HabitsForm(forms.Form):
    peak_time = forms.ChoiceField(label="Verimli saat", choices=StudentProfile.PeakTime.choices, widget=forms.RadioSelect)
    rest_weekday = forms.ChoiceField(
        label="Dinlenme günü",
        choices=[("", "Yok")] + [(str(i), name) for i, name in enumerate(WEEKDAY_NAMES)],
        required=False,
        widget=forms.RadioSelect,
    )

    def clean_rest_weekday(self):
        value = self.cleaned_data["rest_weekday"]
        return int(value) if value != "" else None


class GoalsAndMockForm(forms.Form):
    """Step 5: optional goals and optional results of a mock exam the student already solved."""

    target_department = forms.CharField(label="Hedef bölüm", max_length=100, required=False)
    target_tyt_net = forms.DecimalField(label="Hedef TYT neti", min_value=0, decimal_places=2, max_digits=5, required=False)
    target_ayt_net = forms.DecimalField(label="Hedef AYT/YDT neti", min_value=0, decimal_places=2, max_digits=5, required=False)

    def __init__(self, *args, sessions=(), subjects_by_session=None, **kwargs):
        """`sessions`: ExamSession list of the track; `subjects_by_session`: session id -> Subject list."""
        super().__init__(*args, **kwargs)
        self.sessions = list(sessions)
        self.subjects_by_session = subjects_by_session or {}
        self._caps = {}
        for session in self.sessions:
            subjects = self.subjects_by_session.get(session.pk, [])
            self._caps[session.code] = sum(s.question_count for s in subjects)
            self.fields[f"date_{session.code}"] = forms.DateField(
                label="Deneme tarihi", required=False, widget=forms.DateInput(attrs={"type": "date"}),
            )
            for subject in subjects:
                for key, label in (("c", "Doğru"), ("w", "Yanlış"), ("b", "Boş")):
                    self.fields[f"{key}_{subject.pk}"] = forms.IntegerField(
                        label=f"{subject.name} – {label}", min_value=0, required=False,
                        widget=forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "placeholder": "0"}),
                    )
        first, second = (self.sessions + [None, None])[:2]
        self.tyt_cap = self._caps.get(first.code) if first else None
        self.ayt_cap = self._caps.get(second.code) if second else None

    def clean_target_tyt_net(self):
        value = self.cleaned_data["target_tyt_net"]
        if value is not None and self.tyt_cap is not None and value > self.tyt_cap:
            raise forms.ValidationError(f"Hedef net en fazla {self.tyt_cap} olabilir.")
        return value

    def clean_target_ayt_net(self):
        value = self.cleaned_data["target_ayt_net"]
        if value is not None and self.ayt_cap is not None and value > self.ayt_cap:
            raise forms.ValidationError(f"Hedef net en fazla {self.ayt_cap} olabilir.")
        return value

    def _session_filled(self, session):
        for subject in self.subjects_by_session.get(session.pk, []):
            for key in ("c", "w", "b"):
                if self.cleaned_data.get(f"{key}_{subject.pk}") not in (None, ""):
                    return True
        return False

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()
        for session in self.sessions:
            if not self._session_filled(session):
                continue
            taken = cleaned.get(f"date_{session.code}")
            if taken is not None and taken > today:
                self.add_error(f"date_{session.code}", "Deneme tarihi gelecekte olamaz.")
            for subject in self.subjects_by_session.get(session.pk, []):
                total = sum(cleaned.get(f"{k}_{subject.pk}") or 0 for k in ("c", "w", "b"))
                if total > subject.question_count:
                    self.add_error(
                        f"c_{subject.pk}",
                        f"{subject.name} için doğru, yanlış ve boş toplamı {subject.question_count} soruyu geçemez.",
                    )
        return cleaned

    def filled_sessions(self):
        """(session, taken_on, {subject: (correct, wrong, blank)}) for every session the student filled in."""
        out = []
        for session in self.sessions:
            if not self._session_filled(session):
                continue
            scores = {}
            for subject in self.subjects_by_session.get(session.pk, []):
                scores[subject] = tuple(self.cleaned_data.get(f"{k}_{subject.pk}") or 0 for k in ("c", "w", "b"))
            out.append((session, self.cleaned_data.get(f"date_{session.code}") or timezone.localdate(), scores))
        return out

    def session_blocks(self):
        """Template helper: bound fields grouped by session and subject."""
        blocks = []
        for session in self.sessions:
            subjects = []
            for subject in self.subjects_by_session.get(session.pk, []):
                subjects.append({
                    "subject": subject,
                    "correct": self[f"c_{subject.pk}"],
                    "wrong": self[f"w_{subject.pk}"],
                    "blank": self[f"b_{subject.pk}"],
                })
            blocks.append({"session": session, "date": self[f"date_{session.code}"], "subjects": subjects})
        return blocks
