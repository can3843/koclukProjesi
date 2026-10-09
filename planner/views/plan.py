from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from planner.engine.phases import PHASE_BY_CODE, PHASES
from planner.models import Plan, PlanTopic
from planner.services import build_plan, exam_countdown, get_active_plan

FOCUS_TOPIC_COUNT = 8
DROPPED_REASONS = (PlanTopic.ReasonCode.NO_TIME, PlanTopic.ReasonCode.BIG_TOPIC_LATE)

DISCLAIMER = "Bu bir tahmindir; gerçek sonucun çalışma düzenine, denemelerine ve sınav gününe göre değişir."


def _plan_or_build(request):
    plan = get_active_plan(request.user)
    if plan is None:
        plan = build_plan(request.user, reason=Plan.Reason.MANUAL)
    return plan


def _question_text(avg):
    avg = Decimal(avg)
    return "1'den az soru" if avg < 1 else f"~{round(avg)} soru"


def _target_verdict(target, session):
    """Compare a target net with the estimated range of one session."""
    if target is None or session is None:
        return None
    target = float(target)
    if target > session["high"]:
        return "ambitious"
    if target >= session["low"]:
        return "on_track"
    return "may_exceed"


def _target_rows(profile, projection, scenario):
    rows = []
    sessions = {s["code"]: s for s in projection["sessions"]}
    plus = {s["code"]: s for s in (scenario or {}).get("sessions", [])}
    codes = list(sessions)
    targets = [(profile.target_tyt_net, codes[0] if codes else None), (profile.target_ayt_net, codes[1] if len(codes) > 1 else None)]
    for target, code in targets:
        verdict = _target_verdict(target, sessions.get(code))
        if verdict:
            rows.append({
                "code": code, "target": target, "verdict": verdict,
                "session": sessions[code], "plus": plus.get(code),
            })
    return rows


@login_required
def plan_report(request):
    plan = _plan_or_build(request)
    profile = request.student_profile
    countdown = exam_countdown(profile)
    plan_topics = list(plan.plan_topics.select_related("topic__subject__test__session").order_by("sequence", "id"))

    focus = [pt for pt in plan_topics if pt.included][:FOCUS_TOPIC_COUNT]
    groups = {}
    for pt in plan_topics:
        if pt.included or pt.reason_code not in DROPPED_REASONS:
            continue
        group = groups.setdefault(pt.topic.subject_id, {"subject": pt.topic.subject, "items": [], "minutes": 0})
        group["items"].append({
            "topic": pt.topic,
            "questions": _question_text(pt.topic.avg_questions),
            "hours": max(1, round(pt.need_minutes / 60)),
            "late": pt.reason_code == PlanTopic.ReasonCode.BIG_TOPIC_LATE,
        })
        group["minutes"] += pt.need_minutes
    dropped_groups = sorted(
        groups.values(),
        key=lambda g: (g["subject"].test.session.order, g["subject"].test.order, g["subject"].order),
    )
    for group in dropped_groups:
        group["hours"] = max(1, round(group["minutes"] / 60))
    budget = plan.budget
    study_minutes = budget["new_any"] + budget["new_small"] + budget["practice"]
    projection = plan.projection
    rule = PHASE_BY_CODE[plan.phase_code]

    context = {
        "plan": plan,
        "countdown": countdown,
        "total_minutes": budget["raw_total"],
        "study_minutes": study_minutes,
        "required_minutes": plan.required_minutes,
        "fits_all": budget.get("fits_all", False),
        "coverage": round(plan.coverage_ratio * 100),
        "sessions": projection["sessions"],
        "tests": projection["tests"],
        "target_rows": _target_rows(profile, projection, projection.get("plus_hour")),
        "focus": focus,
        "dropped_groups": dropped_groups,
        "dropped_count": sum(len(g["items"]) for g in dropped_groups),
        "rule": rule,
        "disclaimer": DISCLAIMER,
    }
    return render(request, "planner/report.html", context)


def _phase_segments(today, exam_date, current_code):
    """Phase timeline between today and exam day, with date ranges."""
    days_left_now = (exam_date - today).days
    segments = []
    upper = None
    for rule in PHASES:
        lowest = rule.min_days_left
        highest = upper if upper is not None else max(days_left_now, lowest)
        upper = lowest - 1
        seg_hi = min(highest, days_left_now)
        seg_lo = max(lowest, 1)
        if seg_hi < seg_lo:
            continue
        segments.append({
            "rule": rule,
            "start": exam_date - timedelta(days=seg_hi),
            "end": exam_date - timedelta(days=seg_lo),
            "days": seg_hi - seg_lo + 1,
            "current": rule.code == current_code,
        })
    return segments


@login_required
def plan_roadmap(request):
    plan = _plan_or_build(request)
    profile = request.student_profile
    countdown = exam_countdown(profile)
    today = timezone.localdate()

    plan_topics = list(plan.plan_topics.select_related("topic__subject__test__session").order_by("sequence", "id"))
    subjects = {}
    for pt in plan_topics:
        if not pt.included:
            continue
        group = subjects.setdefault(pt.topic.subject_id, {"subject": pt.topic.subject, "topics": []})
        group["topics"].append({
            "topic": pt.topic,
            "sequence": pt.sequence,
            "week": None if pt.start_day is None else pt.start_day // 7 + 1,
            "prerequisite": pt.reason_code == PlanTopic.ReasonCode.PREREQUISITE,
        })
    ordered = sorted(subjects.values(), key=lambda g: (g["subject"].test.session.order, g["subject"].test.order, g["subject"].order))
    dropped = [pt for pt in plan_topics if not pt.included and pt.reason_code in DROPPED_REASONS]
    dropped_count = len(dropped)

    return render(request, "planner/roadmap.html", {
        "plan": plan,
        "countdown": countdown,
        "segments": _phase_segments(today, countdown["date"], plan.phase_code) if countdown else [],
        "groups": ordered,
        "dropped_count": dropped_count,
        "dropped": [
            {"topic": pt.topic, "hours": max(1, round(pt.need_minutes / 60)), "late": pt.reason_code == PlanTopic.ReasonCode.BIG_TOPIC_LATE}
            for pt in sorted(dropped, key=lambda pt: (pt.topic.subject.test.session.order, pt.topic.subject.test.order, pt.topic.subject.order, pt.topic.order))
        ],
        "rule": PHASE_BY_CODE[plan.phase_code],
    })
