from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts import ratelimit
from catalog.models import Topic, Track
from planner.engine.capacity import count_days_by_kind
from planner.forms import HabitsForm, TimeForm, TrackForm
from planner.models import PlanTopic, TopicProgress
from planner.services import (
    change_track, delete_account, ensure_progress_rows, first_session, get_active_plan, set_topic_override,
    track_topics, update_levels, update_schedule,
)

TOO_MANY = "Çok fazla deneme yaptın. Biraz bekleyip tekrar dene."


def _as_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _schedule_forms(request, profile):
    initial_time = {"weekday_minutes": profile.weekday_minutes, "weekend_minutes": profile.weekend_minutes}
    initial_habits = {
        "peak_time": profile.peak_time,
        "rest_weekday": "" if profile.rest_weekday is None else str(profile.rest_weekday),
    }
    data = request.POST if request.method == "POST" and request.POST.get("section") == "schedule" else None
    return TimeForm(data, initial=initial_time), HabitsForm(data, initial=initial_habits)


@login_required
def settings_home(request):
    profile = request.student_profile
    section = request.POST.get("section") if request.method == "POST" else None
    time_form, habits_form = _schedule_forms(request, profile)
    tracks = list(Track.objects.filter(exam=profile.exam).prefetch_related("tests__session").order_by("id"))
    track_form = TrackForm(
        request.POST if section == "track" else None, tracks=tracks, initial={"track": str(profile.track_id or "")},
    )

    if section == "schedule" and time_form.is_valid() and habits_form.is_valid():
        changed = update_schedule(
            request.user, time_form.cleaned_data["weekday_minutes"], time_form.cleaned_data["weekend_minutes"],
            habits_form.cleaned_data["rest_weekday"], habits_form.cleaned_data["peak_time"],
        )
        messages.success(request, "Planını yeni vaktine göre yeniledim. ✅" if changed else "Ayarların kaydedildi. ✅")
        return redirect("settings")

    if section == "track" and track_form.is_valid():
        track = next(t for t in tracks if str(t.pk) == track_form.cleaned_data["track"])
        if track.pk == profile.track_id:
            messages.info(request, "Alanın zaten bu.")
            return redirect("settings")
        if not request.POST.get("confirm"):
            track_form.add_error("track", "Alanı değiştirmek için aşağıdaki kutuyu işaretleyerek onaylamalısın.")
        else:
            change_track(request.user, track)
            messages.success(request, f"Alanın {track.name} olarak değişti; planını yeniden kurdum.")
            return redirect("settings")

    exam_date = first_session(profile.exam).date
    weekdays, weekends = count_days_by_kind(timezone.localdate(), exam_date)
    weekday_value = _as_int(time_form["weekday_minutes"].value(), profile.weekday_minutes)
    weekend_value = _as_int(time_form["weekend_minutes"].value(), profile.weekend_minutes)
    return render(request, "planner/settings.html", {
        "profile": profile,
        "time_form": time_form, "habits_form": habits_form, "track_form": track_form,
        "tracks": tracks,
        "weekdays": weekdays, "weekends": weekends,
        "weekday_value": weekday_value, "weekend_value": weekend_value,
        "total_hours": round((weekdays * weekday_value + weekends * weekend_value) / 60),
    })


@login_required
def settings_levels(request):
    profile = request.student_profile
    ensure_progress_rows(request.user, profile.track)
    topics = list(track_topics(profile.track))

    if request.method == "POST":
        levels = {}
        for topic in topics:
            raw = request.POST.get(f"level_{topic.pk}")
            if raw in ("0", "1", "2"):
                levels[topic.pk] = int(raw)
        changed = update_levels(request.user, levels)
        if changed:
            messages.success(request, f"{changed} konunun seviyesini güncelledim ve planını yeniledim. ✅")
        else:
            messages.info(request, "Değişen bir seviye yok.")
        return redirect("settings_levels")

    progress = {p.topic_id: p for p in TopicProgress.objects.filter(user=request.user)}
    groups = []
    for topic in topics:
        row = progress[topic.pk]
        if not groups or groups[-1]["subject"].pk != topic.subject_id:
            groups.append({"subject": topic.subject, "topics": []})
        groups[-1]["topics"].append({"topic": topic, "level": row.level, "learned": row.state == TopicProgress.State.LEARNED})
    return render(request, "planner/settings_levels.html", {"groups": groups})


def _topic_plan_state(row, plan_topic):
    """(label, css class, can add, can take out, has a manual override) for one row of the topics page."""
    override = row.user_override
    if row.state == TopicProgress.State.LEARNED:
        return "Öğrenildi", "learned", False, False, False
    if override == TopicProgress.Override.FORCE_EXCLUDE:
        return "Sen çıkardın", "out", True, False, True
    if override == TopicProgress.Override.FORCE_INCLUDE:
        return "Sen ekledin", "in", False, True, True
    if plan_topic is not None and plan_topic.included:
        return "Planda", "in", False, True, False
    if plan_topic is not None and plan_topic.reason_code in (PlanTopic.ReasonCode.NO_TIME, PlanTopic.ReasonCode.BIG_TOPIC_LATE):
        return "Vakit yetmedi", "out", True, False, False
    return "Zaten iyi", "good", True, False, False


@login_required
def settings_topics(request):
    profile = request.student_profile
    plan = get_active_plan(request.user)
    plan_topics = {pt.topic_id: pt for pt in plan.plan_topics.all()} if plan else {}
    progress = {p.topic_id: p for p in TopicProgress.objects.filter(user=request.user)}
    groups = []
    for topic in track_topics(profile.track):
        row = progress.get(topic.pk)
        if row is None:
            continue
        if not groups or groups[-1]["subject"].pk != topic.subject_id:
            groups.append({"subject": topic.subject, "topics": []})
        label, css, can_include, can_exclude, has_override = _topic_plan_state(row, plan_topics.get(topic.pk))
        groups[-1]["topics"].append({
            "topic": topic, "label": label, "css": css,
            "can_include": can_include, "can_exclude": can_exclude, "has_override": has_override,
        })
    return render(request, "planner/settings_topics.html", {"groups": groups})


OVERRIDES = {
    "force_include": TopicProgress.Override.FORCE_INCLUDE,
    "force_exclude": TopicProgress.Override.FORCE_EXCLUDE,
    "auto": None,
}


@login_required
@require_POST
def topic_override(request, topic_id):
    """Add a topic to the plan anyway, take it out, or give it back to the automatic choice."""
    profile = request.student_profile
    topic = get_object_or_404(Topic, pk=topic_id, is_active=True, subject__test__tracks=profile.track)
    choice = request.POST.get("override")
    if choice not in OVERRIDES:
        raise Http404
    ensure_progress_rows(request.user, profile.track)
    changed = set_topic_override(request.user, topic, OVERRIDES[choice])
    if not changed:
        messages.info(request, "Bu konu için yapılacak bir değişiklik yok.")
    elif choice == "force_include":
        messages.success(request, f"{topic.name} konusunu plana ekledim.")
    elif choice == "force_exclude":
        messages.success(request, f"{topic.name} konusunu plandan çıkardım.")
    else:
        messages.success(request, f"{topic.name} konusunu otomatik seçime bıraktım.")
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = f"/ayarlar/konular/#ders-{topic.subject_id}"
    return redirect(target)


@login_required
def account_delete(request):
    """Delete the account and every piece of its data, after the password is confirmed."""
    error, status = None, 200
    if request.method == "POST":
        if ratelimit.is_limited("login", request, ratelimit.LOGIN_FAILURES):
            error, status = TOO_MANY, 429
        elif not request.user.check_password(request.POST.get("password", "")):
            ratelimit.record("login", request, ratelimit.LOGIN_FAILURES)
            error = "Parola hatalı."
        else:
            user = request.user
            logout(request)
            delete_account(user)
            messages.success(request, "Hesabın ve tüm verilerin silindi. Kendine iyi bak! 👋")
            return redirect("home")
    return render(request, "planner/account_delete.html", {"error": error}, status=status)
