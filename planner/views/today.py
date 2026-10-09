from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from django.urls import reverse

from planner.engine.adaptation import pace_is_low
from planner.engine.phases import PHASE_BY_CODE
from planner.models import MockExam, StudentProfile, Task
from planner.services import (
    TaskError, active_rescope_ids, complete_task, compute_pace, current_streak, day_summary, ensure_daily_state,
    exam_countdown, skip_task, undo_task, unseen_review,
)

MAX_INFO_CARDS = 2
RING_LENGTH = 213.63  # circumference of the progress ring in the SVG (2 * pi * 34)
DEFAULT_COLOR = "#5B5BD6"
KIND_ICONS = {"learn": "📖", "practice": "✏️", "review": "🔁", "mock": "📝", "mock_review": "🔍"}
PEAK_LABELS = {
    StudentProfile.PeakTime.MORNING: "☀️ Sabah ilk iş",
    StudentProfile.PeakTime.NOON: "🌤️ Öğle verimli saatinde",
    StudentProfile.PeakTime.EVENING: "🌆 Akşam verimli saatinde",
    StudentProfile.PeakTime.NIGHT: "🌙 Gece verimli saatinde",
}
WEEKDAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
DONE_ALL_MESSAGE = "Bugünü tamamladın! Yarın görüşürüz 👋"
PREP_ITEMS = [
    "Kimliğini ve sınava giriş belgeni hazırla.",
    "Sınav yerine nasıl gideceğini önceden planla.",
    "Düzenli uyu; son geceyi erken yat.",
    "Sınav sabahı güzel bir kahvaltı yap.",
]


def greeting(now):
    hour = now.hour
    if 5 <= hour < 12:
        return "Günaydın", "☀️"
    if 12 <= hour < 18:
        return "İyi günler", "👋"
    if 18 <= hour < 23:
        return "İyi akşamlar", "🌙"
    return "İyi geceler", "🌙"


def decorate(tasks, profile):
    """Attach display helpers (color, icon, peak label) to tasks."""
    label = PEAK_LABELS.get(profile.peak_time, "") if profile else ""
    mock_ids = [t.pk for t in tasks if t.kind == Task.Kind.MOCK]
    linked = set(MockExam.objects.filter(task_id__in=mock_ids).values_list("task_id", flat=True)) if mock_ids else set()
    for task in tasks:
        task.mock_linked = task.pk in linked
        task.color = task.subject.color if task.subject_id else DEFAULT_COLOR
        task.icon = KIND_ICONS.get(task.kind, "•")
        task.peak_label = label if task.is_peak and task.kind == Task.Kind.LEARN else ""
        task.takes_counts = task.kind in (Task.Kind.PRACTICE, Task.Kind.REVIEW)
    return tasks


def _stash_notices(request, notices):
    """Daily notices are computed once per day: keep them in the session until /bugun/ shows them."""
    pending = request.session.get("daily_notices", {})
    if notices.get("missed"):
        pending["missed"] = notices["missed"]
    if notices.get("phase_changed"):
        pending["phase_changed"] = notices["phase_changed"]
    request.session["daily_notices"] = pending


def _info_cards(request, profile, countdown, today):
    """Information cards, at most two at a time, most important first (§13 Faz 5 order):
    scope suggestion > new phase > weekly review > missed day > pace warning > estimated exam date."""
    pending = request.session.pop("daily_notices", {})
    cards = []
    rescope_ids = active_rescope_ids(profile, today)
    if rescope_ids:
        cards.append({
            "kind": "warning", "icon": "🧭",
            "text": f"Planın gerisinde kalıyorsun. {len(rescope_ids)} konuyu şimdilik bırakmayı önerebilirim; karar senin.",
            "link": reverse("rescope"), "link_text": "Öneriye bak",
        })
    if pending.get("phase_changed"):
        rule = PHASE_BY_CODE[pending["phase_changed"]]
        cards.append({"kind": "info", "icon": "🗓️", "text": f"Yeni döneme geçtin: {rule.name}. {rule.focus}"})
    review = unseen_review(request.user)
    if review is not None:
        cards.append({
            "kind": "info", "icon": "📅", "text": review.message,
            "link": reverse("weekly_reviews"), "link_text": "Haftalık değerlendirmeni gör",
        })
    if pending.get("missed"):
        cards.append({"kind": "info", "icon": "💜", "text": "Dün çalışamadın, sorun değil. Görevlerini önümüzdeki günlere yaydım."})
    pace = compute_pace(request.user, today)
    if pace_is_low(pace) and not rescope_ids:
        cards.append({
            "kind": "info", "icon": "🌱",
            "text": f"Son iki haftada planının %{round(pace * 100)}'ini yapabildin. Sorun değil; küçük adımlarla devam edelim.",
        })
    if countdown and countdown["estimated"]:
        cards.append({
            "kind": "warning", "icon": "📅",
            "text": "Sınav tarihi tahmini. ÖSYM takvimi açıklanınca planını güncelleriz.",
        })
    return cards[:MAX_INFO_CARDS]


@login_required
def today_view(request):
    today = timezone.localdate()
    profile = request.student_profile
    notices = ensure_daily_state(request.user, today)
    _stash_notices(request, notices)
    profile.refresh_from_db(fields=["rescope_proposal", "rescope_snoozed_until"])  # the daily sync may have changed them

    countdown = exam_countdown(profile, today)
    exam_over = countdown is not None and countdown["date"] <= today
    tasks = decorate(
        list(Task.objects.filter(user=request.user, date=today).select_related("subject", "topic").order_by("order", "id")),
        profile,
    )
    summary = day_summary(request.user, today)
    shown = [t for t in tasks if t.status != Task.Status.MISSED]
    is_rest = profile.rest_weekday is not None and profile.rest_weekday == today.weekday()
    word, emoji = greeting(timezone.localtime())
    percent = round(100 * summary["done_minutes"] / summary["planned_minutes"]) if summary["planned_minutes"] else 0

    return render(request, "planner/today.html", {
        "greeting": word, "emoji": emoji,
        "first_name": request.user.first_name,
        "tasks": shown,
        "summary": summary,
        "percent": percent,
        "ring_offset": round(RING_LENGTH * (1 - percent / 100), 2),
        "all_done": summary["total_count"] > 0 and summary["done_count"] == summary["total_count"],
        "streak": current_streak(request.user, today),
        "cards": _info_cards(request, profile, countdown, today),
        "is_rest": is_rest,
        "exam_over": exam_over,
        "prep": PREP_ITEMS if countdown and 0 < countdown["days"] <= 7 else None,
        "countdown": countdown,
    })


def _day_label(day, today):
    if day == today:
        return "Bugün"
    if day == today + timedelta(days=1):
        return "Yarın"
    return f"{WEEKDAY_NAMES[day.weekday()]} {day.day}.{day.month:02d}"


@login_required
def week_view(request):
    today = timezone.localdate()
    profile = request.student_profile
    _stash_notices(request, ensure_daily_state(request.user, today))
    end = today + timedelta(days=7)
    by_date = {}
    for task in decorate(
        list(Task.objects.filter(user=request.user, date__gte=today, date__lt=end).select_related("subject").order_by("date", "order", "id")),
        profile,
    ):
        by_date.setdefault(task.date, []).append(task)
    days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        tasks = by_date.get(day, [])
        days.append({
            "date": day,
            "label": _day_label(day, today),
            "tasks": tasks,
            "minutes": sum(t.minutes for t in tasks if t.status in (Task.Status.PENDING, Task.Status.DONE)),
            "is_rest": profile.rest_weekday is not None and profile.rest_weekday == day.weekday(),
            "is_today": offset == 0,
        })
    return render(request, "planner/week.html", {"days": days})


def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "") or request.headers.get("X-Requested-With") == "XMLHttpRequest"


@login_required
@require_POST
def task_action(request, pk, action):
    """complete / skip / undo a task; JSON for the app, a redirect for plain form posts."""
    task = get_object_or_404(Task, pk=pk, user=request.user)  # somebody else's task is a 404
    today = timezone.localdate()
    profile = request.student_profile
    try:
        if action == "complete":
            counts = (None, None, None) if request.POST.get("skip_counts") else (
                request.POST.get("correct"), request.POST.get("wrong"), request.POST.get("blank"))
            complete_task(task, *counts, today=today)
        elif action == "skip":
            skip_task(task, today)
        else:
            undo_task(task, today)
    except TaskError as error:
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": str(error)}, status=error.status)
        messages.error(request, str(error))
        return redirect("today")

    task = Task.objects.select_related("subject", "topic").get(pk=pk)
    summary = day_summary(request.user, task.date)
    if action == "complete":
        done_all = summary["total_count"] and summary["done_count"] == summary["total_count"]
        message = DONE_ALL_MESSAGE if done_all else f"Harika, {summary['done_count']}/{summary['total_count']} tamam! 💪"
    elif action == "skip":
        message = "Sorun değil, bu görevi önümüzdeki günlere yaydım. 💜"
    else:
        message = "Geri aldım."

    if not _wants_json(request):
        messages.success(request, message)
        return redirect("today")
    return JsonResponse({
        "ok": True,
        "task": {"id": task.pk, "status": task.status},
        "day": summary,
        "streak": current_streak(request.user, today),
        "message": message,
        "html": render_to_string("partials/task_card.html", {"task": decorate([task], profile)[0]}, request=request),
    })
