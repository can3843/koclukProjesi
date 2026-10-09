from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone

from catalog.models import Exam, Track
from planner.models import Plan, StudentProfile
from planner.services import build_plan

FROZEN_TODAY = date(2027, 1, 4)  # a Monday, 166 days before the (estimated) TYT date
DATA_FILE = Path(settings.BASE_DIR) / "data" / "yks_2027.json"
PASSWORD = "gizli-parola-123"


def seed_catalog():
    call_command("seed_exam_data", str(DATA_FILE), stdout=StringIO())


def make_user(email="elif@example.com", name="Elif"):
    return get_user_model().objects.create_user(email, PASSWORD, first_name=name)


def make_onboarded_user(email="elif@example.com", track="SAY", weekday=180, weekend=300, rest=None, build=True):
    """User with a finished onboarding (catalog must be seeded)."""
    user = make_user(email)
    exam = Exam.objects.get(slug="yks-2027")
    profile = StudentProfile.objects.create(
        user=user, exam=exam, track=Track.objects.get(exam=exam, code=track),
        weekday_minutes=weekday, weekend_minutes=weekend, rest_weekday=rest,
        onboarding_step=5, onboarding_completed_at=timezone.now(),
    )
    if build:
        build_plan(user, today=FROZEN_TODAY, reason=Plan.Reason.ONBOARDING)
    return user, profile


class FrozenTodayMixin:
    """Freeze `timezone.localdate()` so tests do not depend on the real date."""

    def setUp(self):
        super().setUp()
        patcher = patch("django.utils.timezone.localdate", return_value=FROZEN_TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)
