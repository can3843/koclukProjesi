"""Day by day capacity, mock calendar and budgets (CLAUDE.md §6.3, §6.4)."""

from collections import Counter
from datetime import timedelta

from . import config
from .phases import phase_for
from .types import Budget, DayPlan


def exam_day(inp):
    return inp.sessions[0].date


def raw_minutes_for(day, inp):
    """Raw capacity of one calendar day before buffer and phase effects."""
    if inp.rest_weekday is not None and day.weekday() == inp.rest_weekday:
        return 0
    base = inp.weekend_minutes if day.weekday() >= 5 else inp.weekday_minutes
    return base + inp.extra_minutes_per_day


def total_raw_minutes(today, exam_date, weekday_minutes, weekend_minutes, rest_weekday=None):
    """Plain sum of what the student can study from today up to (not including) exam day."""
    total = 0
    day = today
    while day < exam_date:
        if rest_weekday is None or day.weekday() != rest_weekday:
            total += weekend_minutes if day.weekday() >= 5 else weekday_minutes
        day += timedelta(days=1)
    return total


def count_days_by_kind(today, exam_date):
    """(weekday count, weekend day count) between today and exam day (exam day excluded)."""
    weekdays = weekends = 0
    day = today
    while day < exam_date:
        if day.weekday() >= 5:
            weekends += 1
        else:
            weekdays += 1
        day += timedelta(days=1)
    return weekdays, weekends


def _round_to(value, step):
    return round(value / step) * step


def _early_tyt_only(inp):
    """P6 rule: only the first session is mocked early if most advanced topics are untouched."""
    first = inp.session_codes[0] if inp.session_codes else None
    if first is None:
        return False
    test_session = {test.slug: test.session_code for test in inp.tests}
    subject_session = {s.id: test_session.get(s.test_slug) for s in inp.subjects}
    advanced = [t for t in inp.topics if subject_session.get(t.subject_id) not in (None, first)]
    if not advanced:
        return False
    level0 = sum(1 for t in advanced if inp.states.get(t.id) is None or inp.states[t.id].level == 0)
    return level0 / len(advanced) > config.EARLY_TYT_ONLY_LEVEL0_SHARE


def build_days(inp):
    """Return one DayPlan per day from today up to the day before the exam, in order.

    Mocks that are already known (taken, missed or still planned) keep the calendar stable
    when the plan is recomputed on a later day.
    """
    exam = exam_day(inp)
    durations = {s.code: s.duration_minutes for s in inp.sessions}
    codes = inp.session_codes or tuple(durations)
    tyt_only_early = _early_tyt_only(inp)

    known = sorted(inp.known_mock_dates)
    last_mock = known[-1] if known else None
    mocks_in_week = Counter(d.isocalendar()[:2] for d in known)
    p0_mocks = sum(1 for d in known if 0 <= (exam - d).days <= 7)
    mock_index = len(known)
    carry_analysis = 0.0

    days = []
    day = inp.today
    while day < exam:
        days_left = (exam - day).days
        rule = phase_for(days_left)
        raw = raw_minutes_for(day, inp)
        is_rest = raw == 0 and inp.rest_weekday is not None and day.weekday() == inp.rest_weekday

        if rule.code == "P0":
            raw *= config.FINAL_WEEK_CAPACITY_FACTOR
        if days_left == 1:
            raw = min(raw, config.LAST_DAY_MAX_MIN)
        net = _round_to(raw * (1 - config.BUFFER_RATIO), config.CAPACITY_ROUNDING_MIN) if raw else 0.0

        # analysis of an earlier mock that did not fit on its own day
        available = float(net)
        analysis_today = 0.0
        if carry_analysis > 0 and net >= config.MIN_BLOCK_MIN:
            analysis_today = min(carry_analysis, available)
            carry_analysis -= analysis_today
            available -= analysis_today

        week_key = day.isocalendar()[:2]
        can_mock = (
            not is_rest
            and day.weekday() in rule.mock_weekdays
            and days_left > config.MOCK_FREE_LAST_DAYS
            and (last_mock is None or (day - last_mock).days >= rule.mock_gap_days)
            and mocks_in_week.get(week_key, 0) < rule.mock_max_per_week
            and not (rule.code == "P0" and p0_mocks >= 1)
        )

        mock_session = None
        mock_duration = 0.0
        mock_minutes = 0.0
        if can_mock and codes:
            early = tyt_only_early and (day - inp.today).days < config.EARLY_TYT_ONLY_DAYS
            mock_session = codes[0] if early else codes[mock_index % len(codes)]
            mock_duration = float(durations.get(mock_session, 0))
            mock_minutes = mock_duration + config.MOCK_ANALYSIS_MIN
            mock_index += 1
            last_mock = day
            mocks_in_week[week_key] += 1
            if rule.code == "P0":
                p0_mocks += 1
            if available >= mock_duration + config.MOCK_ANALYSIS_MIN:
                analysis_today += config.MOCK_ANALYSIS_MIN
                study = available - mock_duration - config.MOCK_ANALYSIS_MIN
            else:
                carry_analysis += config.MOCK_ANALYSIS_MIN  # analysis moves to the next free day
                study = max(0.0, available - mock_duration)
        else:
            study = available

        new = study * rule.new
        days.append(
            DayPlan(
                date=day,
                days_left=days_left,
                phase_code=rule.code,
                raw_minutes=float(raw),
                net_minutes=float(net),
                is_rest=is_rest,
                mock_session=mock_session,
                mock_minutes=float(mock_minutes),
                new_any=new if rule.code in ("P6", "P4", "P3") else 0.0,
                new_small=new if rule.code == "P2" else 0.0,
                practice=study * rule.practice,
                review=study * rule.review,
                mock_duration=mock_duration,
                analysis_minutes=analysis_today,
            )
        )
        day += timedelta(days=1)
    return days


def sum_budget(days):
    return Budget(
        raw_total=round(sum(d.raw_minutes for d in days)),
        mock_minutes=round(sum(d.mock_minutes for d in days)),
        new_any=round(sum(d.new_any for d in days)),
        new_small=round(sum(d.new_small for d in days)),
        practice=round(sum(d.practice for d in days)),
        review=round(sum(d.review for d in days)),
    )
