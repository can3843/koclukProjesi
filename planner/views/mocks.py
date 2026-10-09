from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from catalog.models import ExamSession, Subject, Topic
from planner.forms import MockForm
from planner.models import MockExam
from planner.services import add_topic_to_plan, plan_suggestions, record_mock, set_weak_topics

NET_DIGITS = Decimal("0.01")


def _net(scores):
    return sum((s.net for s in scores), Decimal("0")).quantize(NET_DIGITS)


def _track_sessions(profile):
    return list(ExamSession.objects.filter(tests__tracks=profile.track).distinct().order_by("order"))


def _summaries(mocks):
    """Total net and question count of each mock, for lists."""
    rows = []
    for mock in mocks:
        scores = list(mock.scores.all())
        rows.append({
            "mock": mock,
            "net": _net(scores),
            "questions": sum(s.subject.question_count for s in scores),
            "weak_count": mock.weak_topics.count(),
        })
    return rows


@login_required
def mock_list(request):
    mocks = (
        MockExam.objects.filter(user=request.user).select_related("session")
        .prefetch_related("scores__subject", "weak_topics")
    )
    return render(request, "planner/mock_list.html", {"rows": _summaries(mocks)})


def _weak_step(request, mock_id):
    mock = get_object_or_404(MockExam.objects.select_related("session"), pk=mock_id, user=request.user)
    if request.method == "POST":
        chosen = [int(v) for v in request.POST.getlist("weak") if v.isdigit()]
        topics = set_weak_topics(request.user, mock, chosen)
        if topics:
            messages.success(request, "Zorlandığın konular planda daha çok yer alacak. 💪")
        return redirect("mock_detail", pk=mock.pk)

    chosen = set(mock.weak_topics.values_list("pk", flat=True))
    groups = []
    for score in mock.scores.select_related("subject").order_by("subject__order"):
        topics = Topic.objects.filter(subject=score.subject, is_active=True).order_by("order")
        groups.append({
            "subject": score.subject,
            "topics": [{"topic": t, "checked": t.pk in chosen} for t in topics],
            "open": score.wrong + score.blank > 0,
        })
    return render(request, "planner/mock_weak.html", {"mock": mock, "groups": groups})


@login_required
def mock_add(request):
    profile = request.student_profile
    weak_id = request.GET.get("zayif") or request.POST.get("zayif")
    if weak_id:
        if not weak_id.isdigit():
            raise Http404
        return _weak_step(request, int(weak_id))

    sessions = _track_sessions(profile)
    code = request.GET.get("oturum") or request.POST.get("oturum")
    if not code:
        return render(request, "planner/mock_choose.html", {"sessions": sessions})
    session = next((s for s in sessions if s.code == code), None)
    if session is None:
        raise Http404

    subjects = Subject.objects.filter(test__tracks=profile.track, test__session=session).order_by("test__order", "order")
    task_id = request.GET.get("gorev") or request.POST.get("gorev") or ""
    form = MockForm(
        request.POST if request.method == "POST" else None, subjects=subjects,
        initial={"taken_on": timezone.localdate()},
    )
    if request.method == "POST" and form.is_valid():
        mock = record_mock(
            request.user, session, form.cleaned_data["taken_on"], form.scores(),
            task_id=int(task_id) if task_id.isdigit() else None,
        )
        messages.success(request, "Deneme sonucun kaydedildi. 👏")
        return redirect(f"{reverse('mock_add')}?zayif={mock.pk}")
    return render(request, "planner/mock_form.html", {
        "session": session, "form": form, "rows": form.rows(), "task_id": task_id,
    })


@login_required
def mock_detail(request, pk):
    mock = get_object_or_404(MockExam.objects.select_related("session"), pk=pk, user=request.user)
    scores = list(mock.scores.select_related("subject").order_by("subject__test__order", "subject__order"))
    return render(request, "planner/mock_detail.html", {
        "mock": mock,
        "scores": scores,
        "net": _net(scores),
        "questions": sum(s.subject.question_count for s in scores),
        "weak": list(mock.weak_topics.select_related("subject")),
        "suggestions": plan_suggestions(request.user, mock),
    })


@login_required
@require_POST
def mock_add_topic(request, pk, topic_id):
    """"Do you want this weak topic in the plan?" - yes."""
    mock = get_object_or_404(MockExam, pk=pk, user=request.user)
    topic = get_object_or_404(mock.weak_topics, pk=topic_id)
    add_topic_to_plan(request.user, topic)
    messages.success(request, f"{topic.name} konusunu plana ekledim.")
    return redirect("mock_detail", pk=mock.pk)
