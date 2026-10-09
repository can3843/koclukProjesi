from .services import exam_countdown


def countdown(request):
    """Top bar chip: days until the exam, with an "estimated" badge when the date is not official."""
    profile = getattr(request, "student_profile", None)
    if profile is None or not profile.is_onboarded:
        return {}
    return {"exam_countdown": exam_countdown(profile)}
