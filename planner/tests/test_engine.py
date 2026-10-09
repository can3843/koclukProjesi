"""Engine tests on a tiny artificial catalog (no database). Scenario numbers refer to CLAUDE.md §6.10."""

from datetime import date, timedelta

from django.test import SimpleTestCase

from planner.engine import config, make_plan
from planner.engine.capacity import build_days, count_days_by_kind, total_raw_minutes
from planner.engine.phases import phase_for
from planner.engine.types import (
    MockResult, PlanInput, SessionInfo, SubjectInfo, TestInfo, TopicInfo, TopicState,
)

TODAY = date(2027, 1, 4)  # a Monday


def make_catalog(hour_scale=1.0):
    tests = (
        TestInfo("t1", "Test 1", "TYT", 40),
        TestInfo("t2", "Test 2", "AYT", 40),
    )
    subjects = (
        SubjectInfo(1, "Mat", "t1", 1, 30),
        SubjectInfo(2, "Geo", "t1", 2, 10),
        SubjectInfo(3, "Fiz", "t2", 1, 40),
    )
    # id, subject, order, avg questions, hours, prerequisites
    rows = [
        (1, 1, 1, 4, 6, ()), (2, 1, 2, 6, 8, (1,)), (3, 1, 3, 5, 5, (2,)),
        (4, 1, 4, 5, 4, ()), (5, 1, 5, 6, 10, ()), (6, 1, 6, 4, 3, ()),
        (7, 2, 1, 3, 4, ()), (8, 2, 2, 3, 5, (7,)), (9, 2, 3, 4, 6, ()),
        (10, 3, 1, 10, 5, ()), (11, 3, 2, 10, 8, (10,)), (12, 3, 3, 12, 12, ()), (13, 3, 4, 8, 4, ()),
    ]
    order = {s.id: s.order for s in subjects}
    topics = tuple(
        TopicInfo(tid, sid, order[sid], o, f"T{tid}", float(avg), hours * hour_scale, 2, tuple(pre))
        for tid, sid, o, avg, hours, pre in rows
    )
    return tests, subjects, topics


def make_input(days_left=200, weekday=180, weekend=300, rest=None, hour_scale=1.0, states=None, mocks=(), **extra):
    tests, subjects, topics = make_catalog(hour_scale)
    exam = TODAY + timedelta(days=days_left)
    return PlanInput(
        today=TODAY,
        sessions=(SessionInfo("TYT", exam, 165), SessionInfo("AYT", exam + timedelta(days=1), 180)),
        session_codes=("TYT", "AYT"),
        tests=tests,
        subjects=subjects,
        topics=topics,
        states=states or {},
        weekday_minutes=weekday,
        weekend_minutes=weekend,
        rest_weekday=rest,
        mocks=mocks,
        **extra,
    )


def reasons(result):
    return {t.topic_id: t.reason_code for t in result.topics}


def included_ids(result):
    return {t.topic_id for t in result.topics if t.included}


class PhaseTests(SimpleTestCase):
    def test_phase_boundaries(self):
        expected = {200: "P6", 151: "P6", 150: "P4", 91: "P4", 90: "P3", 61: "P3", 60: "P2", 31: "P2",
                    30: "P1", 8: "P1", 7: "P0", 0: "P0"}
        for days_left, code in expected.items():
            self.assertEqual(phase_for(days_left).code, code, days_left)

    def test_phase_shares_sum_to_one(self):
        for days_left in (200, 120, 70, 40, 20, 3):
            rule = phase_for(days_left)
            self.assertAlmostEqual(rule.new + rule.practice + rule.review, 1.0)


class CapacityTests(SimpleTestCase):
    def test_buffer_is_removed_and_rounded_to_five_minutes(self):
        day = build_days(make_input(days_left=200, weekday=300))[0]
        self.assertEqual(day.net_minutes, 255)  # 300 * 0.85

    def test_weekend_uses_weekend_minutes(self):
        days = build_days(make_input(days_left=20, weekday=120, weekend=240))
        saturday = next(d for d in days if d.date.weekday() == 5)
        self.assertEqual(saturday.raw_minutes, 240)

    def test_scenario_7_rest_day_has_no_capacity_and_no_mock(self):
        days = build_days(make_input(days_left=120, rest=6))
        sundays = [d for d in days if d.date.weekday() == 6]
        self.assertTrue(sundays)
        for day in sundays:
            self.assertTrue(day.is_rest)
            self.assertEqual(day.net_minutes, 0)
            self.assertIsNone(day.mock_session)
            self.assertEqual(day.practice + day.review + day.new_any + day.new_small, 0)

    def test_scenario_6_final_week_capacity_and_last_day(self):
        days = build_days(make_input(days_left=30, weekday=240, weekend=360))
        final_week = [d for d in days if d.days_left <= 7]
        for day in final_week:
            full = 360 if day.date.weekday() >= 5 else 240
            if day.days_left > 1:
                self.assertAlmostEqual(day.raw_minutes, full * config.FINAL_WEEK_CAPACITY_FACTOR)
        last = days[-1]
        self.assertEqual(last.days_left, 1)
        self.assertLessEqual(last.raw_minutes, config.LAST_DAY_MAX_MIN)

    def test_scenario_6_no_mock_in_last_three_days_and_at_most_one_in_final_week(self):
        days = build_days(make_input(days_left=40))
        for day in days:
            if day.days_left <= config.MOCK_FREE_LAST_DAYS:
                self.assertIsNone(day.mock_session, day.date)
        self.assertLessEqual(sum(1 for d in days if d.phase_code == "P0" and d.mock_session), 1)

    def test_mocks_prefer_weekends_and_alternate_sessions(self):
        days = build_days(make_input(days_left=200, weekday=240, weekend=480))
        mocks = [d for d in days if d.mock_session]
        self.assertGreater(len(mocks), 5)
        p6 = [d for d in mocks if d.phase_code == "P6"]
        self.assertTrue(all(d.date.weekday() >= 5 for d in p6))
        # P6 allows one mock per 14 days
        for first, second in zip(p6, p6[1:]):
            self.assertGreaterEqual((second.date - first.date).days, 14)

    def test_early_mocks_are_tyt_only_when_advanced_topics_are_untouched(self):
        days = build_days(make_input(days_left=200, weekday=240, weekend=480))
        early = [d for d in days if d.mock_session and (d.date - TODAY).days < config.EARLY_TYT_ONLY_DAYS]
        self.assertTrue(early)
        self.assertTrue(all(d.mock_session == "TYT" for d in early))

    def test_scenario_5_twenty_days_left_three_mocks_a_week(self):
        days = build_days(make_input(days_left=20, weekday=240, weekend=480))
        by_week = {}
        for day in days:
            if day.mock_session and day.phase_code == "P1":
                by_week.setdefault(day.date.isocalendar()[:2], []).append(day)
        self.assertTrue(by_week)
        self.assertLessEqual(max(len(v) for v in by_week.values()), 3)
        self.assertTrue(any(len(v) == 3 for v in by_week.values()))

    def test_mock_day_deducts_mock_and_analysis_time(self):
        days = build_days(make_input(days_left=120, weekday=240, weekend=600))
        mock_day = next(d for d in days if d.mock_session == "TYT")
        self.assertEqual(mock_day.mock_minutes, 165 + config.MOCK_ANALYSIS_MIN)
        study = mock_day.new_any + mock_day.new_small + mock_day.practice + mock_day.review
        self.assertAlmostEqual(study, max(0, mock_day.net_minutes - mock_day.mock_minutes), places=6)

    def test_helpers_count_days_and_minutes(self):
        exam = TODAY + timedelta(days=14)
        self.assertEqual(count_days_by_kind(TODAY, exam), (10, 4))
        self.assertEqual(total_raw_minutes(TODAY, exam, 100, 200), 10 * 100 + 4 * 200)
        self.assertEqual(total_raw_minutes(TODAY, exam, 100, 200, rest_weekday=0), 8 * 100 + 4 * 200)


class PlanScenarioTests(SimpleTestCase):
    def test_scenario_1_plenty_of_time_includes_everything(self):
        result = make_plan(make_input(days_left=200, weekday=600, weekend=660))
        self.assertEqual(result.coverage_ratio, 1.0)
        self.assertTrue(result.fits_all)
        self.assertEqual(len(included_ids(result)), 13)
        self.assertTrue(all(t.reason_code in ("selected", "prerequisite") for t in result.topics))

    def test_scenario_2_six_months_beginner_three_hours_drops_topics_but_keeps_prerequisites(self):
        inp = make_input(days_left=180, weekday=180, weekend=180, hour_scale=6)
        result = make_plan(inp)
        self.assertFalse(result.fits_all)
        self.assertLess(result.coverage_ratio, 1.0)
        dropped = [t for t in result.topics if not t.included]
        self.assertTrue(dropped)
        self.assertTrue(all(t.reason_code in ("no_time", "big_topic_late") for t in dropped))

        included = included_ids(result)
        topics = {t.id: t for t in inp.topics}
        for tid in included:
            for prereq in topics[tid].prerequisites:
                self.assertIn(prereq, included, f"topic {tid} is included without its prerequisite {prereq}")

    def test_scenario_3_three_months_left_uses_p3_shares_not_p6(self):
        inp = make_input(days_left=85, weekday=240, weekend=240)
        result = make_plan(inp)
        self.assertEqual(result.phase_code, "P3")
        first = build_days(inp)[0]
        study = first.new_any + first.practice + first.review
        self.assertAlmostEqual(first.new_any / study, 0.35, places=3)
        self.assertAlmostEqual(first.practice / study, 0.45, places=3)
        self.assertNotAlmostEqual(first.new_any / study, 0.65, places=2)

    def test_scenario_4_big_level0_topics_are_not_started_in_the_deneme_period(self):
        inp = make_input(days_left=45, weekday=300, weekend=420)
        result = make_plan(inp)
        self.assertEqual(result.phase_code, "P2")
        self.assertEqual(result.budget.new_any, 0)
        self.assertGreater(result.budget.new_small, 0)
        big = {2, 5, 11, 12}  # more than 6 learning hours
        codes = reasons(result)
        for tid in big:
            self.assertEqual(codes[tid], "big_topic_late", tid)
            self.assertNotIn(tid, included_ids(result))

    def test_twenty_days_left_starts_no_new_topic(self):
        result = make_plan(make_input(days_left=20, weekday=300, weekend=420))
        self.assertEqual(result.phase_code, "P1")
        self.assertEqual(result.budget.new_total, 0)
        self.assertEqual(included_ids(result), set())

    def test_level_2_topics_are_cheap_and_marked_already_good_when_time_is_short(self):
        states = {tid: TopicState(level=2) for tid in range(1, 14)}
        full = make_plan(make_input(days_left=200, weekday=240, weekend=300, states=states))
        self.assertTrue(full.fits_all)
        short = make_plan(make_input(days_left=45, weekday=30, weekend=30, states=states))
        self.assertTrue(all(t.reason_code in ("selected", "already_good") for t in short.topics))

    def test_learned_topics_are_not_part_of_the_scope(self):
        states = {1: TopicState(level=2, state="learned")}
        result = make_plan(make_input(days_left=200, states=states))
        self.assertNotIn(1, {t.topic_id for t in result.topics})

    def test_user_excluded_topics_stay_out_and_force_include_goes_first(self):
        states = {4: TopicState(override="force_exclude"), 12: TopicState(override="force_include")}
        result = make_plan(make_input(days_left=45, weekday=120, weekend=120, hour_scale=3, states=states))
        codes = reasons(result)
        self.assertEqual(codes[4], "user_excluded")
        self.assertEqual(codes[12], "selected")

    def test_in_progress_topic_uses_remaining_minutes(self):
        states = {5: TopicState(level=0, state="in_progress", remaining_learn=30, remaining_practice=60)}
        result = make_plan(make_input(days_left=200, states=states))
        topic = next(t for t in result.topics if t.topic_id == 5)
        self.assertEqual(topic.need_minutes, 90)

    def test_sequence_puts_prerequisites_first(self):
        result = make_plan(make_input(days_left=200, weekday=600, weekend=660))
        position = {t.topic_id: t.sequence for t in result.topics}
        self.assertLess(position[1], position[2])
        self.assertLess(position[2], position[3])
        self.assertLess(position[7], position[8])
        self.assertLess(position[10], position[11])
        self.assertEqual(sorted(position.values()), list(range(1, 14)))

    def test_start_days_are_non_decreasing_in_study_order(self):
        result = make_plan(make_input(days_left=200, weekday=600, weekend=660))
        ordered = sorted((t for t in result.topics if t.included and t.start_day is not None), key=lambda t: t.sequence)
        starts = [t.start_day for t in ordered]
        self.assertEqual(starts, sorted(starts))

    def test_required_minutes_cover_all_candidate_topics(self):
        result = make_plan(make_input(days_left=200))
        self.assertEqual(result.required_minutes, round(sum(t.need_minutes for t in result.topics)))

    def test_exam_day_or_past_gives_an_empty_budget_without_crashing(self):
        result = make_plan(make_input(days_left=0))
        self.assertEqual(result.budget.raw_total, 0)
        self.assertEqual(result.phase_code, "P0")


class DeterminismTests(SimpleTestCase):
    def test_scenario_11_same_input_gives_identical_output(self):
        inp = make_input(days_left=120, weekday=150, weekend=240, hour_scale=3)
        self.assertEqual(make_plan(inp), make_plan(inp))

    def test_ties_are_broken_by_subject_and_topic_order(self):
        results = [make_plan(make_input(days_left=90, weekday=90, weekend=90, hour_scale=4)) for _ in range(3)]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])


class ProjectionTests(SimpleTestCase):
    def test_scenario_12_high_end_never_exceeds_question_counts(self):
        states = {tid: TopicState(level=2, solved=100, correct=100, wrong=0) for tid in range(1, 14)}
        inp = make_input(days_left=200, weekday=600, weekend=660, states=states)
        projection = make_plan(inp).projection
        for test in projection.tests:
            self.assertLessEqual(test.high, test.question_count)
            self.assertLessEqual(test.low, test.high)
        for session in projection.sessions:
            self.assertLessEqual(session.high, session.question_count)

    def test_range_is_85_to_105_percent_before_the_cap(self):
        projection = make_plan(make_input(days_left=200, weekday=600, weekend=660)).projection
        test = next(t for t in projection.tests if t.test_slug == "t1")
        self.assertLess(test.low, test.high)
        self.assertGreater(test.high, test.now)

    def test_time_helps_more_than_no_time(self):
        poor = make_plan(make_input(days_left=60, weekday=30, weekend=30, hour_scale=5)).projection
        rich = make_plan(make_input(days_left=200, weekday=600, weekend=660)).projection
        self.assertGreater(sum(s.high for s in rich.sessions), sum(s.high for s in poor.sessions))

    def test_scenario_12_calibration_stays_inside_bounds(self):
        base = make_plan(make_input(days_left=200, weekday=600, weekend=660)).projection
        loud = MockResult(nets={1: 999.0, 2: 999.0, 3: 999.0})
        quiet = MockResult(nets={1: 0.0, 2: 0.0, 3: 0.0})
        up = make_plan(make_input(days_left=200, weekday=600, weekend=660, mocks=(loud, loud))).projection
        down = make_plan(make_input(days_left=200, weekday=600, weekend=660, mocks=(quiet, quiet))).projection
        low_bound, high_bound = config.MOCK_CALIBRATION_BOUNDS
        for b, u, d in zip(base.tests, up.tests, down.tests):
            self.assertLessEqual(u.low, round(b.low * high_bound) + 1)
            self.assertGreaterEqual(d.high, round(b.high * low_bound) - 1)
            self.assertLessEqual(d.high, b.high)

    def test_pace_correction_only_after_fourteen_days(self):
        slow_new_plan = make_plan(make_input(days_left=200, weekday=600, weekend=660, pace=0.2, plan_age_days=3)).projection
        normal = make_plan(make_input(days_left=200, weekday=600, weekend=660)).projection
        self.assertEqual(slow_new_plan, normal)
        slow = make_plan(make_input(days_left=200, weekday=600, weekend=660, pace=0.2, plan_age_days=20)).projection
        self.assertLess(sum(s.high for s in slow.sessions), sum(s.high for s in normal.sessions))

    def test_plus_one_hour_scenario_is_not_worse(self):
        result = make_plan(make_input(days_left=90, weekday=90, weekend=120, hour_scale=4))
        self.assertIsNotNone(result.plus_hour_projection)
        base_total = sum(s.high for s in result.projection.sessions)
        plus_total = sum(s.high for s in result.plus_hour_projection.sessions)
        self.assertGreaterEqual(plus_total, base_total)
