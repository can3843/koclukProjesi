from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from catalog.models import Topic
from planner.engine import config
from planner.models import TopicProgress, WeeklyReview
from planner.services import apply_rescope, compute_rescope, snooze_rescope


@login_required
def weekly_reviews(request):
    reviews = list(WeeklyReview.objects.filter(user=request.user))
    unseen = [r for r in reviews if r.seen_at is None]
    if unseen:
        WeeklyReview.objects.filter(pk__in=[r.pk for r in unseen]).update(seen_at=timezone.now())
    for review in reviews:
        review.week_end = review.week_start + timedelta(days=6)
        review.is_new = review in unseen
    return render(request, "planner/reviews.html", {"reviews": reviews})


@login_required
def rescope(request):
    """The scope suggestion: nothing changes until the student confirms."""
    today = timezone.localdate()
    if request.method == "POST":
        if request.POST.get("action") == "apply":
            dropped = apply_rescope(request.user, today)
            if dropped:
                messages.success(request, "Planını güncelledim. Bırakılan konuları istediğin zaman geri ekleyebilirsin.")
            else:
                messages.success(request, "Şu an kapsamı daraltmaya gerek yok.")
        else:
            snooze_rescope(request.user, today)
            messages.success(request, "Tamam, şimdilik kalsın. Bir hafta sonra tekrar bakarım.")
        return redirect("today")

    topic_ids = compute_rescope(request.user, today)
    topics = {t.pk: t for t in Topic.objects.filter(pk__in=topic_ids).select_related("subject")}
    needs = {
        row.topic_id: row for row in TopicProgress.objects.filter(user=request.user, topic_id__in=topic_ids)
    }
    items = [
        {"topic": topics[tid], "hours": max(1, round(float(topics[tid].learn_hours) * config.NEED_FACTOR[needs[tid].level]))}
        for tid in topic_ids if tid in topics
    ]
    return render(request, "planner/rescope.html", {"items": items})
