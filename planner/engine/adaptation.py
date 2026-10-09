"""Adaptation helpers: missed tasks and the study streak (CLAUDE.md §6.8, §4 streak rule)."""

from datetime import timedelta

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
