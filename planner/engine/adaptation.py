"""Adaptation helpers: missed tasks and the study streak (CLAUDE.md §6.8, §4 streak rule)."""

from dataclasses import replace
from datetime import timedelta

from . import config

STREAK_LOOKBACK_DAYS = 400


def missed_task_ids(tasks, today):
    """Ids of pending tasks whose day is over. `tasks` are (id, date, status) tuples."""
    return [task_id for task_id, day, status in tasks if status == "pending" and day < today]


def compute_streak(done_dates, planned_dates, rest_weekday, today):
    """Number of consecutive study days ending today (or yesterday if today is not done yet).

    A day counts when at least one task was done. A rest day neither counts nor breaks the streak,
    and neither does a day without any planned task.
    """
    if not planned_dates and not done_dates:
        return 0
    first_day = min(set(planned_dates) | set(done_dates))
    streak = 0
    day = today
    for _ in range(STREAK_LOOKBACK_DAYS):
        if day < first_day:
            break
        if day in done_dates:
            streak += 1
        elif day == today:
            pass  # today is not over: it cannot break the streak yet
        elif rest_weekday is not None and day.weekday() == rest_weekday:
            pass
        elif day not in planned_dates:
            pass
        else:
            break
        day -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------- Phase 5: adaptation (CLAUDE.md §6.8)


def raised_boost(boost):
    """A topic marked weak in a mock gets more weight, up to the limit."""
    return min(config.BOOST_MAX, boost + config.BOOST_STEP)


def decayed_boost(boost, weeks):
    """Boosts fade every week, never below 1.0."""
    return max(1.0, boost - config.BOOST_DECAY_PER_WEEK * weeks)


def pace_of(done_minutes, planned_minutes):
    """Done / planned minutes, or None when nothing was planned."""
    if planned_minutes <= 0:
        return None
    return done_minutes / planned_minutes


def pace_is_low(pace):
    return pace is not None and pace < config.PACE_WARNING


def extra_practice_minutes(correct, wrong, blank):
    """Minutes added to a topic after a practice task with weak accuracy (0 if the result is fine)."""
    answered = (correct or 0) + (wrong or 0) + (blank or 0)
    if answered < config.WEAK_PRACTICE_MIN_ANSWERED:
        return 0
    return config.EXTRA_PRACTICE_MIN if (correct or 0) / answered < config.PRACTICE_WEAK_ACCURACY else 0


def rescope_needed(remaining_need, remaining_budget, pace):
    """True when what is left to study does not fit what the student really gets done."""
    if pace is None:
        return False
    return remaining_need > remaining_budget * pace * config.RESCOPE_TOLERANCE


def propose_rescope(inp, current_included, pace):
    """Dry run: topics to drop so that the plan fits the student's real pace. Nothing is saved.

    `current_included` are the ids of the topics still in the plan (not learned yet). Returns the ids that
    would no longer be included, the least valuable (latest in the study order) first.
    """
    from . import make_plan  # imported here: the package imports this module

    if pace is None or pace >= 1:
        return []
    result = make_plan(replace(inp, capacity_factor=max(pace, 0.05)), with_scenario=False)
    kept = {t.topic_id for t in result.topics if t.included}
    # `current_included` is in study order, so walking it backwards puts the least urgent topic first
    return [tid for tid in reversed(list(current_included)) if tid not in kept]
