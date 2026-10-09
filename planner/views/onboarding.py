from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from catalog.models import Exam, ExamSession, Subject, Track
from planner.engine.capacity import count_days_by_kind
from planner.forms import GoalsAndMockForm, HabitsForm, TimeForm, TrackForm
from planner.models import MockExam, MockScore, Plan, StudentProfile, TopicProgress
from planner.services import build_plan, ensure_progress_rows, first_session, track_topics

LAST_STEP = 5
STEP_TITLES = {1: "Sınav ve alan", 2: "Günlük vakit", 3: "Verimli saat", 4: "Konu seviyeleri", 5: "Deneme ve hedef"}


def _post_data(request):
    """Bind forms only on POST (an empty POST body must still count as a submission)."""
    return request.POST if request.method == "POST" else None


def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "")


def _advance(profile, step):
    """Remember how far the student got and move on to the next step."""
    profile.onboarding_step = max(profile.onboarding_step, min(step + 1, LAST_STEP))
    profile.save(update_fields=["onboarding_step"])
    return redirect("onboarding_step", step=min(step + 1, LAST_STEP))


def _context(profile, step, **extra):
    return {"onboarding_mode": True, "step": step, "steps": range(1, LAST_STEP + 1), "step_title": STEP_TITLES[step], "profile": profile, **extra}


@login_required
def onboarding_step(request, step):
    if not 1 <= step <= LAST_STEP:
        raise Http404
    profile, _ = StudentProfile.objects.select_related("exam", "track").get_or_create(user=request.user)
    if profile.is_onboarded:
        return redirect("plan_report")
    if step > profile.onboarding_step or (step > 1 and profile.track_id is None):
        return redirect("onboarding_step", step=profile.onboarding_step if profile.track_id else 1)
    return {1: step_exam, 2: step_time, 3: step_habits, 4: step_levels, 5: step_finish}[step](request, profile)


def step_exam(request, profile):
    exam = Exam.objects.filter(is_active=True).first()
    if exam is None:
        raise Http404
    tracks = list(Track.objects.filter(exam=exam).prefetch_related("tests__session").order_by("id"))
    session = first_session(exam)
    form = TrackForm(_post_data(request), tracks=tracks, initial={"track": str(profile.track_id or "")})
    if request.method == "POST" and form.is_valid():
        profile.exam = exam
        profile.track = next(t for t in tracks if str(t.pk) == form.cleaned_data["track"])
        profile.save(update_fields=["exam", "track"])
        ensure_progress_rows(request.user, profile.track)
        return _advance(profile, 1)
    cards = []
    for t in tracks:
        extra = [f"{test.session.code} {test.name}" for test in t.tests.all() if test.session.pk != session.pk]
        cards.append({"track": t, "summary": " + ".join([f"{session.code}'nin tamamı"] + extra)})
    return render(request, "onboarding/step1.html", _context(profile, 1, exam=exam, session=session, cards=cards, form=form))


def _as_minutes(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def step_time(request, profile):
    exam_date = first_session(profile.exam).date
    form = TimeForm(
        _post_data(request),
        initial={"weekday_minutes": profile.weekday_minutes, "weekend_minutes": profile.weekend_minutes},
    )
    if request.method == "POST" and form.is_valid():
        profile.weekday_minutes = form.cleaned_data["weekday_minutes"]
        profile.weekend_minutes = form.cleaned_data["weekend_minutes"]
        profile.save(update_fields=["weekday_minutes", "weekend_minutes"])
        return _advance(profile, 2)
    weekdays, weekends = count_days_by_kind(timezone.localdate(), exam_date)
    weekday_value = _as_minutes(form["weekday_minutes"].value(), profile.weekday_minutes)
    weekend_value = _as_minutes(form["weekend_minutes"].value(), profile.weekend_minutes)
    total_hours = round((weekdays * weekday_value + weekends * weekend_value) / 60)
    return render(
        request, "onboarding/step2.html",
        _context(profile, 2, form=form, weekdays=weekdays, weekends=weekends, weekday_value=weekday_value,
                 weekend_value=weekend_value, total_hours=total_hours,
                 days_left=max(0, (exam_date - timezone.localdate()).days)),
    )


def step_habits(request, profile):
    form = HabitsForm(
        _post_data(request),
        initial={
            "peak_time": profile.peak_time,
            "rest_weekday": "" if profile.rest_weekday is None else str(profile.rest_weekday),
        },
    )
    if request.method == "POST" and form.is_valid():
        profile.peak_time = form.cleaned_data["peak_time"]
        profile.rest_weekday = form.cleaned_data["rest_weekday"]
        profile.save(update_fields=["peak_time", "rest_weekday"])
        return _advance(profile, 3)
    return render(request, "onboarding/step3.html", _context(profile, 3, form=form))


def _levels_by_subject(user, track):
    progress = {p.topic_id: p for p in TopicProgress.objects.filter(user=user)}
    groups = []
    for topic in track_topics(track):
        subject = topic.subject
        if not groups or groups[-1]["subject"].pk != subject.pk:
            groups.append({"subject": subject, "topics": [], "marked": 0})
        level = progress[topic.pk].level
        groups[-1]["topics"].append({"topic": topic, "level": level})
        groups[-1]["marked"] += 1 if level > 0 else 0
    return groups


def step_levels(request, profile):
    ensure_progress_rows(request.user, profile.track)
    if request.method == "POST":
        if request.POST.get("action") == "next":
            return _advance(profile, 4)
        return _save_subject_levels(request, profile)
    groups = _levels_by_subject(request.user, profile.track)
    return render(request, "onboarding/step4.html", _context(profile, 4, groups=groups))


def _save_subject_levels(request, profile):
    subject_id = request.POST.get("subject", "")
    if not subject_id.isdigit():
        raise Http404
    subject = get_object_or_404(Subject, pk=int(subject_id), test__tracks=profile.track)
    rows = list(TopicProgress.objects.filter(user=request.user, topic__subject=subject, topic__is_active=True))
    quick = request.POST.get("set_all")
    for row in rows:
        raw = quick if quick in ("0", "1", "2") else request.POST.get(f"level_{row.topic_id}")
        if raw in ("0", "1", "2"):
            row.level = row.initial_level = int(raw)
    TopicProgress.objects.bulk_update(rows, ["level", "initial_level"])
    marked = sum(1 for r in rows if r.level > 0)
    if _wants_json(request):
        return JsonResponse({"ok": True, "subject": subject.pk, "marked": marked, "total": len(rows)})
    messages.success(request, f"{subject.name} seviyelerin kaydedildi.")
    return redirect(f"{request.path}#ders-{subject.pk}")


def step_finish(request, profile):
    sessions = list(
        ExamSession.objects.filter(tests__tracks=profile.track).distinct().order_by("order")
    )
    subjects = list(Subject.objects.filter(test__tracks=profile.track).select_related("test").order_by("test__order", "order"))
    by_session = {s.pk: [sub for sub in subjects if sub.test.session_id == s.pk] for s in sessions}
    initial = {
        "target_department": profile.target_department,
        "target_tyt_net": profile.target_tyt_net,
        "target_ayt_net": profile.target_ayt_net,
    }
    form = GoalsAndMockForm(_post_data(request), sessions=sessions, subjects_by_session=by_session, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            profile.target_department = form.cleaned_data["target_department"]
            profile.target_tyt_net = form.cleaned_data["target_tyt_net"]
            profile.target_ayt_net = form.cleaned_data["target_ayt_net"]
            # Mocks can only come from this step before onboarding ends, so a re-submit replaces them.
            MockExam.objects.filter(user=request.user, session__in=sessions).delete()
            for session, taken_on, scores in form.filled_sessions():
                mock = MockExam.objects.create(user=request.user, session=session, taken_on=taken_on)
                MockScore.objects.bulk_create(
                    MockScore(mock=mock, subject=subject, correct=c, wrong=w, blank=b)
                    for subject, (c, w, b) in scores.items()
                )
            profile.onboarding_step = LAST_STEP
            profile.onboarding_completed_at = timezone.now()
            profile.save()
            build_plan(request.user, reason=Plan.Reason.ONBOARDING)
        messages.success(request, "Rotanı çizdim. Hazırsan başlayalım!")
        return redirect("plan_report")
    return render(request, "onboarding/step5.html", _context(profile, 5, form=form, blocks=form.session_blocks()))
