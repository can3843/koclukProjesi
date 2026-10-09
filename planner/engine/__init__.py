"""Pure Python plan engine. It never imports Django and never reads the clock: `today` is an input."""

from dataclasses import replace

from . import config
from .capacity import build_days, exam_day, sum_budget
from .needs import candidate_needs
from .phases import phase_for
from .projection import project
from .selection import select_topics
from .types import PlanResult, TopicResult


def _start_days(days, sequence, needs_by_id):
    """Rough day offset at which learning of each included topic starts, from the daily new-topic budget."""
    starts = {}
    index = 0
    left_today = (days[0].new_any + days[0].new_small) if days else 0.0
    for tid in sequence:
        learn = needs_by_id[tid].learn_need
        if learn <= 0:
            starts[tid] = None
            continue
        while index < len(days) and left_today <= 1e-9:
            index += 1
            left_today = (days[index].new_any + days[index].new_small) if index < len(days) else 0.0
        if index >= len(days):
            starts[tid] = None
            continue
        starts[tid] = index
        while learn > 1e-9 and index < len(days):
            used = min(learn, left_today)
            learn -= used
            left_today -= used
            if left_today <= 1e-9 and learn > 1e-9:
                index += 1
                left_today = (days[index].new_any + days[index].new_small) if index < len(days) else 0.0
    return starts


def make_plan(inp, with_scenario=True):
    """Build the plan for one student: scope, order and estimated net range."""
    exam = exam_day(inp)
    days_left = (exam - inp.today).days
    days = build_days(inp)
    budget = sum_budget(days)

    needs = candidate_needs(inp)
    needs_by_id = {n.topic.id: n for n in needs}
    selection = select_topics(
        needs,
        {"new_any": budget.new_any, "new_small": budget.new_small, "practice": budget.practice},
    )

    sequence = selection.sequence
    positions = {tid: i + 1 for i, tid in enumerate(sequence)}
    starts = _start_days(days, sequence, needs_by_id)

    results = []
    for topic in inp.topics:
        need = needs_by_id.get(topic.id)
        if need is None:  # already learned: not part of the scope
            continue
        included = topic.id in selection.included
        results.append(
            TopicResult(
                topic_id=topic.id,
                included=included,
                sequence=positions.get(topic.id),
                priority=round(need.ratio, 6),
                gain=round(need.gain, 4),
                need_minutes=round(need.need),
                reason_code=selection.reasons[topic.id],
                start_day=starts.get(topic.id),
            )
        )

    total_questions = sum(n.topic.avg_questions for n in needs)
    covered = sum(n.topic.avg_questions for n in needs if n.topic.id in selection.included)
    coverage = covered / total_questions if total_questions > 0 else 1.0
    required = round(sum(n.need for n in needs if not n.user_excluded))
    fits_all = all(n.topic.id in selection.included for n in needs if not n.user_excluded)

    projection = project(inp, sequence, needs_by_id)
    plus_hour = None
    if with_scenario:
        scenario_input = replace(inp, extra_minutes_per_day=inp.extra_minutes_per_day + config.EXTRA_HOUR_SCENARIO_MIN)
        plus_hour = make_plan(scenario_input, with_scenario=False).projection

    return PlanResult(
        phase_code=phase_for(days_left).code,
        days_left=days_left,
        exam_date=exam,
        budget=budget,
        required_minutes=required,
        coverage_ratio=round(coverage, 4),
        fits_all=fits_all,
        topics=tuple(results),
        projection=projection,
        plus_hour_projection=plus_hour,
        mock_count=sum(1 for d in days if d.mock_session),
    )
