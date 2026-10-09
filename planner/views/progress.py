from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.utils.formats import date_format

from catalog.models import ExamSession, Subject
from planner import charts
from planner.engine import make_plan
from planner.models import MockExam, Task, TopicProgress
from planner.services import build_engine_input, current_streak, exam_countdown, get_active_plan, track_topics

from .plan import DISCLAIMER

WEEKS_SHOWN = 8
TOTAL = "toplam"

# (css class, label, symbol): the symbol keeps the map readable without color
STATUS = {
    "learned": ("learned", "Öğrenildi", "✓"),
    "progress": ("progress", "Devam ediyor", "◐"),
    "good": ("good", "Zaten iyi", "★"),
    "out": ("out", "Plan dışı", "–"),
    "todo": ("todo", "Sırada", "○"),
}


def _topic_status(row, in_plan):
    if row.state == TopicProgress.State.LEARNED:
        return STATUS["learned"]
    if row.state == TopicProgress.State.IN_PROGRESS:
        return STATUS["progress"]
    if row.level == 2:
        return STATUS["good"]
    if not in_plan or row.user_override == TopicProgress.Override.FORCE_EXCLUDE:
        return STATUS["out"]
    return STATUS["todo"]


def topic_map(user, profile):
    """Subject by subject: one tile per topic with its state, plus how many topics are ready."""
    progress = {p.topic_id: p for p in TopicProgress.objects.filter(user=user)}
    plan = get_active_plan(user)
    in_plan = set(plan.plan_topics.filter(included=True).values_list("topic_id", flat=True)) if plan else set()
    groups = []
    for topic in track_topics(profile.track):
        row = progress.get(topic.pk)
        if row is None:
            continue
        if not groups or groups[-1]["subject"].pk != topic.subject_id:
            groups.append({"subject": topic.subject, "tiles": [], "ready": 0, "learned": 0})
        css, label, symbol = _topic_status(row, topic.pk in in_plan)
        group = groups[-1]
        group["tiles"].append({"topic": topic, "css": css, "label": label, "symbol": symbol})
        if css == "learned":
            group["learned"] += 1
        if css in ("learned", "good"):
            group["ready"] += 1
    for group in groups:
        total = len(group["tiles"])
        group["total"] = total
        group["percent"] = round(100 * group["ready"] / total) if total else 0
    return groups


def _net(scores):
    return float(sum(s.net for s in scores))


def net_chart(request, user, profile):
    """Line chart of mock nets for the chosen session and the total or one subject (query: ?oturum=TYT&ders=toplam)."""
    sessions = list(ExamSession.objects.filter(tests__tracks=profile.track).distinct().order_by("order"))
    mocks = list(
        MockExam.objects.filter(user=user).select_related("session")
        .prefetch_related("scores__subject").order_by("taken_on", "id")
    )
    by_session = defaultdict(list)
    for mock in mocks:
        by_session[mock.session_id].append(mock)
    tabs = [s for s in sessions if by_session.get(s.pk)]
    if not tabs:
        return None

    chosen = next((s for s in tabs if s.code == request.GET.get("oturum")), tabs[0])
    subjects = list(Subject.objects.filter(test__tracks=profile.track, test__session=chosen).order_by("test__order", "order"))
    subject = next((s for s in subjects if str(s.pk) == request.GET.get("ders")), None)

    points, rows = [], []
    for mock in by_session[chosen.pk]:
        scores = list(mock.scores.all())
        if subject is not None:
            scores = [s for s in scores if s.subject_id == subject.pk]
            if not scores:
                continue
        net = _net(scores)
        label = date_format(mock.taken_on, "j b")
        title = f"{date_format(mock.taken_on, 'j F Y')}: {charts.fmt(net)} net"
        points.append({"label": label, "value": net, "title": title})
        rows.append({"date": mock.taken_on, "net": charts.fmt(net), "mock": mock})

    cap = subject.question_count if subject else sum(s.question_count for s in subjects)
    goal = None
    if subject is None:
        index = sessions.index(chosen)
        target = profile.target_tyt_net if index == 0 else profile.target_ayt_net if index == 1 else None
        goal = float(target) if target is not None else None
    return {
        "tabs": tabs,
        "session": chosen,
        "subjects": subjects,
        "subject": subject,
        "color": f"var(--chart-{sessions.index(chosen) % 3 + 1})",
        "chart": charts.line_chart(points, cap=cap, goal=goal) if points else None,
        "rows": rows,
        "cap": cap,
    }


def weekly_hours(user, today):
    """Study hours of the last weeks (Monday to Sunday); the current week is still running."""
    this_monday = today - timedelta(days=today.weekday())
    first = this_monday - timedelta(weeks=WEEKS_SHOWN - 1)
    done, planned = defaultdict(int), defaultdict(int)
    for day, status, minutes in Task.objects.filter(user=user, date__gte=first, date__lte=today).values_list("date", "status", "minutes"):
        week = day - timedelta(days=day.weekday())
        planned[week] += minutes
        if status == Task.Status.DONE:
            done[week] += minutes
    bars, total_done = [], 0
    for i in range(WEEKS_SHOWN):
        week = first + timedelta(weeks=i)
        total_done += done[week]
        bars.append({
            "label": date_format(week, "j b"),
            "done": round(done[week] / 60, 2),
            "planned": round(planned[week] / 60, 2),
            "title": (
                f"{date_format(week, 'j F')} haftası: {charts.fmt(done[week] / 60, 1)} sa yapıldı, "
                f"{charts.fmt(planned[week] / 60, 1)} sa planlandı"
            ),
            "done_minutes": done[week], "planned_minutes": planned[week], "week": week,
        })
    return {"chart": charts.bar_chart(bars), "rows": bars, "has_data": total_done > 0 or any(b["planned"] for b in bars)}


def projection_rows(user, profile, today):
    """Estimated exam-day net range per session, from the plan as it stands today (pace and mocks included)."""
    countdown = exam_countdown(profile, today)
    if countdown is None or countdown["days"] <= 0:
        return []
    result = make_plan(build_engine_input(user, today), with_scenario=False)
    rows = []
    for session in result.projection.sessions:
        cap = session.question_count or 1
        rows.append({
            "code": session.code, "cap": session.question_count,
            "now": session.now, "low": session.low, "high": session.high,
            "now_pct": round(100 * session.now / cap, 1),
            "low_pct": round(100 * session.low / cap, 1),
            "width_pct": max(1.5, round(100 * (session.high - session.low) / cap, 1)),
        })
    return rows


@login_required
def progress_view(request):
    today = timezone.localdate()
    profile = request.student_profile
    user = request.user

    done_minutes = Task.objects.filter(user=user, status=Task.Status.DONE).aggregate(total=Sum("minutes"))["total"] or 0
    questions = TopicProgress.objects.filter(user=user).aggregate(solved=Sum("questions_solved"), correct=Sum("questions_correct"))
    solved = questions["solved"] or 0
    week_start = today - timedelta(days=today.weekday())
    week_minutes = Task.objects.filter(user=user, status=Task.Status.DONE, date__gte=week_start, date__lte=today).aggregate(total=Sum("minutes"))["total"] or 0

    return render(request, "planner/progress.html", {
        "streak": current_streak(user, today),
        "stats": {
            "total_hours": round(done_minutes / 60, 1),
            "week_minutes": week_minutes,
            "solved": solved,
            "accuracy": round(100 * (questions["correct"] or 0) / solved) if solved else None,
        },
        "projection": projection_rows(user, profile, today),
        "disclaimer": DISCLAIMER,
        "groups": topic_map(user, profile),
        "net": net_chart(request, user, profile),
        "weekly": weekly_hours(user, today),
        "legend": [STATUS[k] for k in ("learned", "progress", "good", "todo", "out")],
    })
