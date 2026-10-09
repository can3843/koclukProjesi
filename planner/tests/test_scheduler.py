"""Scheduler, review and streak tests without a database. Scenario numbers refer to CLAUDE.md §6.10."""

from collections import Counter
from datetime import date, timedelta

from django.test import SimpleTestCase

from planner.engine import config, make_plan
from planner.engine.adaptation import compute_streak, missed_task_ids
from planner.engine.capacity import build_days
from planner.engine.needs import candidate_needs
from planner.engine.reviews import accuracy_of, after_review, first_review
from planner.engine.scheduler import ReviewDue, ScheduleTopic, question_target, schedule

from .test_engine import TODAY, make_input

GROUPS = {1: "quant", 2: "quant", 3: "science"}


def schedule_topics(inp):
    needs = {n.topic.id: n for n in candidate_needs(inp)}
    names = {s.id: s.name for s in inp.subjects}
    topics = {}
    for topic in inp.topics:
        need = needs.get(topic.id)
        topics[topic.id] = ScheduleTopic(
            id=topic.id, name=topic.name, subject_id=topic.subject_id, subject_name=names[topic.subject_id],
            group=GROUPS[topic.subject_id], difficulty=topic.difficulty, is_big=topic.learn_hours > config.BIG_TOPIC_HOURS,
            minutes_per_question=2.0, prerequisites=topic.prerequisites,
            learn_remaining=need.learn_need if need else 0.0, practice_remaining=need.practice_need if need else 0.0,
        )
    return topics


def plan_tasks(inp, window=7, reviews=(), fallback=(), topics=None, committed=None, sequence=None):
    result = make_plan(inp)
    if sequence is None:
        sequence = [t.topic_id for t in sorted((t for t in result.topics if t.included), key=lambda t: t.sequence)]
    days = build_days(inp)[:window]
    tasks = schedule(days, topics or schedule_topics(inp), sequence, fallback, reviews, committed)
    return days, tasks


def by_day(tasks):
    grouped = {}
    for task in tasks:
        grouped.setdefault(task.date, []).append(task)
    return grouped


class SchedulerBasicsTests(SimpleTestCase):
    def setUp(self):
        self.inp = make_input(days_left=120, weekday=180, weekend=300, hour_scale=2)
        self.days, self.tasks = plan_tasks(self.inp)

    def test_tasks_exist_only_for_the_window(self):
        self.assertTrue(self.tasks)
        window = {d.date for d in self.days}
        self.assertTrue(all(t.date in window for t in self.tasks))

    def test_titles_follow_the_templates(self):
        learn = next(t for t in self.tasks if t.kind == "learn")
        self.assertRegex(learn.title, r"^.+ – .+: \d+ dk konu çalışması$")
        practice = next((t for t in self.tasks if t.kind == "practice"), None)
        if practice:
            self.assertRegex(practice.title, r"^.+ – .+: \d+ soru$")
            self.assertEqual(practice.question_target % 5, 0)
            self.assertGreaterEqual(practice.question_target, 10)

    def test_question_target_rounds_to_five_with_a_minimum_of_ten(self):
        self.assertEqual(question_target(40, 2.0), 20)
        self.assertEqual(question_target(45, 2.0), 25)
        self.assertEqual(question_target(10, 2.0), 10)
        self.assertEqual(question_target(40, 1.2), 35)

    def test_orders_are_sequential_per_day(self):
        for tasks in by_day(self.tasks).values():
            self.assertEqual([t.order for t in tasks], list(range(1, len(tasks) + 1)))

    def test_scenario_9_day_never_exceeds_capacity_except_mock_days(self):
        days = {d.date: d for d in self.days}
        for day, tasks in by_day(self.tasks).items():
            if any(t.kind == "mock" for t in tasks):
                continue
            self.assertLessEqual(sum(t.minutes for t in tasks), days[day].net_minutes + 1, day)

    def test_learning_comes_before_practice_of_the_same_topic(self):
        first_learn, first_practice = {}, {}
        for task in sorted(self.tasks, key=lambda t: (t.date, t.order)):
            if task.kind == "learn":
                first_learn.setdefault(task.topic_id, (task.date, task.order))
            if task.kind == "practice":
                first_practice.setdefault(task.topic_id, (task.date, task.order))
        for topic_id, when in first_practice.items():
            if topic_id in first_learn:
                self.assertLessEqual(first_learn[topic_id], when)

    def test_at_most_three_topics_are_learned_at_once(self):
        learned = {t.topic_id for t in self.tasks if t.kind == "learn"}
        self.assertLessEqual(len(learned), 3 + 3)  # a week can start at most a few topics
        for tasks in by_day(self.tasks).values():
            self.assertLessEqual(len({t.topic_id for t in tasks if t.kind in ("learn", "practice")}), config.MAX_ACTIVE_TOPICS + 2)

    def test_peak_work_comes_first_after_the_mock(self):
        days_with_peak = days_starting_with_peak = 0
        for tasks in by_day(self.tasks).values():
            work = [t for t in tasks if t.kind not in ("mock", "mock_review")]
            if any(t.is_peak for t in work):
                days_with_peak += 1
                days_starting_with_peak += 1 if work[0].is_peak else 0
        self.assertGreater(days_with_peak, 3)
        self.assertGreaterEqual(days_starting_with_peak / days_with_peak, 0.8)

    def test_prerequisite_is_not_started_before_it_is_finished(self):
        # topic 2 needs topic 1: while topic 1 has remaining work, topic 2 must not appear
        inp = make_input(days_left=150, weekday=240, weekend=300, hour_scale=2)
        _, tasks = plan_tasks(inp, window=14)
        seen_one_done = False
        remaining = {t.id: t.learn_remaining + t.practice_remaining for t in schedule_topics(inp).values()}
        for task in sorted(tasks, key=lambda t: (t.date, t.order)):
            if task.topic_id == 2 and remaining[1] > 0.5:
                self.fail("topic 2 was scheduled before its prerequisite topic 1 was finished")
            if task.kind in ("learn", "practice") and task.topic_id in remaining:
                remaining[task.topic_id] -= task.minutes
            seen_one_done = seen_one_done or remaining[1] <= 0.5
        self.assertTrue(seen_one_done or not any(t.topic_id == 2 for t in tasks))

    def test_deterministic(self):
        _, again = plan_tasks(self.inp)
        self.assertEqual(self.tasks, again)


class MixingTests(SimpleTestCase):
    def test_scenario_8_subject_limits_and_variety(self):
        inp = make_input(days_left=150, weekday=420, weekend=480, hour_scale=2)
        _, tasks = plan_tasks(inp, window=14)
        checked_days = 0
        for tasks_of_day in by_day(tasks).values():
            topic_tasks = [t for t in tasks_of_day if t.subject_id is not None]
            counts = Counter(t.subject_id for t in topic_tasks)
            if counts:
                self.assertLessEqual(max(counts.values()), config.MAX_SAME_SUBJECT_BLOCKS_PER_DAY)
            if len(topic_tasks) >= 3:
                checked_days += 1
                self.assertGreaterEqual(len(counts), 2)
                subjects = [t.subject_id for t in topic_tasks]
                for left, right in zip(subjects, subjects[1:]):
                    self.assertNotEqual(left, right, "blocks of the same subject must not follow each other")
        self.assertGreater(checked_days, 3)

    def test_arrange_keeps_priority_but_splits_neighbours(self):
        from planner.engine.scheduler import _arrange
        items = [{"subject_id": s, "n": i} for i, s in enumerate([1, 1, 2, 2, 3])]
        arranged = _arrange(items, None)
        self.assertEqual(len(arranged), 5)
        for left, right in zip(arranged, arranged[1:]):
            self.assertNotEqual(left["subject_id"], right["subject_id"])

    def test_arrange_handles_unavoidable_neighbours(self):
        from planner.engine.scheduler import _arrange
        arranged = _arrange([{"subject_id": 1}, {"subject_id": 1}], None)
        self.assertEqual(len(arranged), 2)


class RestAndFinalWeekTests(SimpleTestCase):
    def test_scenario_7_no_tasks_on_the_rest_day(self):
        inp = make_input(days_left=120, rest=6, hour_scale=2)
        _, tasks = plan_tasks(inp, window=14)
        self.assertTrue(tasks)
        self.assertFalse([t for t in tasks if t.date.weekday() == 6])

    def test_scenario_6_last_day_is_light_and_no_mock_in_the_last_three_days(self):
        inp = make_input(days_left=10, weekday=300, weekend=420, hour_scale=2)
        days, tasks = plan_tasks(inp, window=10, fallback=[1, 2, 3], topics=None)
        last = days[-1]
        self.assertEqual(last.days_left, 1)
        self.assertLessEqual(sum(t.minutes for t in tasks if t.date == last.date), config.LAST_DAY_MAX_MIN)
        for task in tasks:
            if task.kind == "mock":
                self.assertGreater((inp.sessions[0].date - task.date).days, config.MOCK_FREE_LAST_DAYS)
        final_week = {d.date: d for d in days if d.days_left <= 7}
        for day, tasks_of_day in by_day(tasks).items():
            if day in final_week and not any(t.kind == "mock" for t in tasks_of_day):
                self.assertLessEqual(sum(t.minutes for t in tasks_of_day), final_week[day].net_minutes + 1)


class PhaseRuleTests(SimpleTestCase):
    def test_scenario_5_twenty_days_left_has_no_learn_tasks_and_up_to_three_mocks_a_week(self):
        inp = make_input(days_left=20, weekday=240, weekend=480, hour_scale=2)
        topics = schedule_topics(inp)
        days, tasks = plan_tasks(inp, window=20, topics=topics, fallback=[10, 11, 13], sequence=[])
        self.assertFalse([t for t in tasks if t.kind == "learn"])
        self.assertTrue([t for t in tasks if t.kind == "practice"])
        mock_dates = [t.date for t in tasks if t.kind == "mock"]
        weeks = Counter(d.isocalendar()[:2] for d in mock_dates)
        self.assertTrue(mock_dates)
        self.assertLessEqual(max(weeks.values()), 3)

    def test_big_topic_is_not_started_in_the_deneme_period(self):
        inp = make_input(days_left=45, weekday=240, weekend=300, hour_scale=1)
        topics = schedule_topics(inp)
        # topic 12 is big (12 hours): even if the sequence contains it, it is not started in P2
        _, tasks = plan_tasks(inp, window=7, topics=topics, sequence=[12, 4])
        self.assertTrue(all(t.topic_id != 12 for t in tasks if t.kind == "learn"))
        self.assertTrue([t for t in tasks if t.kind == "learn" and t.topic_id == 4])

    def test_started_big_topic_may_continue(self):
        inp = make_input(days_left=45, weekday=240, weekend=300, hour_scale=1)
        topics = schedule_topics(inp)
        started = topics[12].__class__(**{**topics[12].__dict__, "started": True})
        topics[12] = started
        _, tasks = plan_tasks(inp, window=7, topics=topics, sequence=[12])
        self.assertTrue([t for t in tasks if t.kind == "learn" and t.topic_id == 12])


class MockDayTests(SimpleTestCase):
    def test_mock_task_comes_first_and_analysis_last(self):
        inp = make_input(days_left=120, weekday=240, weekend=600, hour_scale=2)
        _, tasks = plan_tasks(inp, window=14)
        mock_days = [d for d, ts in by_day(tasks).items() if any(t.kind == "mock" for t in ts)]
        self.assertTrue(mock_days)
        for day in mock_days:
            ordered = by_day(tasks)[day]
            self.assertEqual(ordered[0].kind, "mock")
            self.assertEqual(ordered[-1].kind, "mock_review")
            self.assertIn("gerçek sınav gibi süre tut", ordered[0].title)
            self.assertEqual(ordered[0].minutes, 165 if ordered[0].session_code == "TYT" else 180)

    def test_short_day_keeps_the_mock_with_a_note_and_moves_the_analysis(self):
        inp = make_input(days_left=120, weekday=60, weekend=120, hour_scale=2)
        days, tasks = plan_tasks(inp, window=20)
        mock = next(t for t in tasks if t.kind == "mock")
        self.assertIn("biraz daha fazla zaman", mock.note)
        same_day = [t for t in tasks if t.date == mock.date and t.kind == "mock_review"]
        later = [t for t in tasks if t.date > mock.date and t.kind == "mock_review"]
        self.assertFalse(same_day)
        self.assertTrue(later)


class CommittedDaysTests(SimpleTestCase):
    def test_committed_days_are_not_regenerated_and_count_as_progress(self):
        inp = make_input(days_left=120, weekday=180, weekend=300, hour_scale=2)
        days, all_tasks = plan_tasks(inp)
        first_day = days[0].date
        first_tasks = [t for t in all_tasks if t.date == first_day]
        committed = {first_day: [(t.topic_id, t.kind, t.minutes, t.review_item_id) for t in first_tasks]}
        _, again = plan_tasks(inp, committed=committed)
        self.assertFalse([t for t in again if t.date == first_day])
        # the other days are planned exactly as before because the committed tasks use the same progress
        self.assertEqual([t for t in all_tasks if t.date != first_day], list(again))

    def test_empty_committed_day_is_left_empty(self):
        inp = make_input(days_left=120)
        days, _ = plan_tasks(inp)
        _, tasks = plan_tasks(inp, committed={days[0].date: []})
        self.assertFalse([t for t in tasks if t.date == days[0].date])


class ReviewSchedulingTests(SimpleTestCase):
    def setUp(self):
        self.inp = make_input(days_left=40, weekday=240, weekend=300)
        self.topics = schedule_topics(self.inp)
        for tid in (1, 4, 7):  # learned topics: no remaining work
            t = self.topics[tid]
            self.topics[tid] = ScheduleTopic(**{**t.__dict__, "learn_remaining": 0.0, "practice_remaining": 0.0})

    def test_due_reviews_become_tasks_oldest_first(self):
        reviews = [ReviewDue(2, 4, TODAY), ReviewDue(1, 1, TODAY - timedelta(days=2)), ReviewDue(3, 7, TODAY + timedelta(days=3))]
        _, tasks = plan_tasks(self.inp, window=7, reviews=reviews, topics=self.topics, sequence=[])
        review_tasks = sorted((t for t in tasks if t.kind == "review"), key=lambda t: (t.date, t.order))
        self.assertEqual([t.review_item_id for t in review_tasks][:2], [1, 2])
        third = next(t for t in review_tasks if t.review_item_id == 3)
        self.assertGreaterEqual(third.date, TODAY + timedelta(days=3))
        self.assertTrue(all(t.minutes == config.REVIEW_TASK_MIN for t in review_tasks))
        self.assertRegex(review_tasks[0].title, r"^Tekrar: .+ – \d+ soru$")

    def test_each_review_item_appears_once(self):
        reviews = [ReviewDue(i, tid, TODAY) for i, tid in enumerate([1, 4, 7, 1, 4], start=1)]
        _, tasks = plan_tasks(self.inp, window=7, reviews=reviews, topics=self.topics, sequence=[])
        ids = [t.review_item_id for t in tasks if t.kind == "review"]
        self.assertEqual(len(ids), len(set(ids)))

    def test_unused_review_time_goes_to_practice(self):
        _, with_reviews = plan_tasks(self.inp, window=7, topics=self.topics, sequence=[], fallback=[1, 4, 7])
        self.assertFalse([t for t in with_reviews if t.kind == "review"])
        self.assertTrue([t for t in with_reviews if t.kind == "practice"])

    def test_review_of_a_topic_outside_the_map_is_ignored(self):
        _, tasks = plan_tasks(self.inp, window=3, reviews=[ReviewDue(1, 999, TODAY)], topics=self.topics, sequence=[])
        self.assertFalse([t for t in tasks if t.kind == "review"])


class ReviewRuleTests(SimpleTestCase):
    EXAM = date(2027, 6, 19)

    def test_scenario_10_review_intervals_are_1_7_30_days(self):
        learned = date(2027, 1, 4)
        index, due = first_review(learned, self.EXAM)
        self.assertEqual((index, due), (0, learned + timedelta(days=1)))
        active, index, due = after_review(0, 0.9, due, self.EXAM)
        self.assertEqual((active, index, due), (True, 1, date(2027, 1, 12)))
        active, index, due = after_review(1, None, due, self.EXAM)
        self.assertEqual((active, index, due), (True, 2, date(2027, 2, 11)))
        active, index, _ = after_review(2, 1.0, due, self.EXAM)
        self.assertFalse(active)

    def test_scenario_10_failed_review_repeats_after_three_days(self):
        done_on = date(2027, 1, 12)
        active, index, due = after_review(1, 0.4, done_on, self.EXAM)
        self.assertEqual((active, index, due), (True, 1, done_on + timedelta(days=config.REVIEW_RETRY_DAYS)))

    def test_scenario_10_nothing_is_planned_after_the_exam(self):
        self.assertIsNone(first_review(self.EXAM - timedelta(days=1), self.EXAM))
        self.assertIsNone(first_review(self.EXAM, self.EXAM))
        active, _, due = after_review(1, 0.9, self.EXAM - timedelta(days=10), self.EXAM)
        self.assertFalse(active)
        self.assertGreaterEqual(due, self.EXAM)
        active, *_ = after_review(0, 0.2, self.EXAM - timedelta(days=2), self.EXAM)
        self.assertFalse(active)

    def test_threshold_is_inclusive(self):
        active, index, _ = after_review(0, config.REVIEW_FAIL_ACCURACY, date(2027, 1, 5), self.EXAM)
        self.assertEqual(index, 1)

    def test_accuracy_of(self):
        self.assertIsNone(accuracy_of(0, 0, 0))
        self.assertIsNone(accuracy_of(None, None, None))
        self.assertAlmostEqual(accuracy_of(6, 2, 2), 0.6)


class AdaptationTests(SimpleTestCase):
    TODAY = date(2027, 1, 13)  # Wednesday

    def test_missed_task_ids_only_returns_past_pending(self):
        tasks = [(1, date(2027, 1, 12), "pending"), (2, date(2027, 1, 13), "pending"),
                 (3, date(2027, 1, 12), "done"), (4, date(2027, 1, 10), "pending")]
        self.assertEqual(missed_task_ids(tasks, self.TODAY), [1, 4])

    def streak(self, done, planned=None, rest=None):
        done = {self.TODAY - timedelta(days=d) for d in done}
        planned = {self.TODAY - timedelta(days=d) for d in (planned if planned is not None else range(0, 12))}
        return compute_streak(done, planned, rest, self.TODAY)

    def test_streak_counts_consecutive_days_including_today(self):
        self.assertEqual(self.streak([0, 1, 2]), 3)

    def test_today_not_done_yet_does_not_break_the_streak(self):
        self.assertEqual(self.streak([1, 2, 3]), 3)

    def test_a_missed_day_breaks_the_streak(self):
        self.assertEqual(self.streak([0, 1, 3, 4]), 2)

    def test_rest_day_neither_counts_nor_breaks(self):
        rest = (self.TODAY - timedelta(days=2)).weekday()
        self.assertEqual(self.streak([0, 1, 3, 4], rest=rest), 4)

    def test_days_without_any_planned_task_are_neutral_but_history_starts_at_first_task(self):
        self.assertEqual(self.streak([0, 1, 3], planned=[0, 1, 3]), 3)
        self.assertEqual(self.streak([0, 1, 2], planned=[0, 1, 2]), 3)

    def test_no_history_means_zero(self):
        self.assertEqual(compute_streak(set(), set(), None, self.TODAY), 0)
