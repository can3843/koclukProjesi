"""Pure adaptation rules and coach messages (CLAUDE.md §6.8, §8.6)."""

from datetime import date

from django.test import SimpleTestCase

from planner.engine import config, make_plan
from planner.engine.adaptation import (
    decayed_boost, extra_practice_minutes, pace_is_low, pace_of, propose_rescope, raised_boost, rescope_needed,
)
from planner.engine.capacity import build_days
from planner.messages import TIERS, pick, weekly_message

from .test_engine import make_input


class BoostTests(SimpleTestCase):
    def test_boost_rises_in_steps_and_never_above_the_maximum(self):
        boost = 1.0
        seen = []
        for _ in range(6):
            boost = raised_boost(boost)
            seen.append(boost)
        self.assertEqual(seen[:4], [1.25, 1.5, 1.75, 2.0])
        self.assertEqual(seen[4:], [config.BOOST_MAX, config.BOOST_MAX])

    def test_boost_fades_each_week_but_not_below_one(self):
        self.assertAlmostEqual(decayed_boost(1.5, 1), 1.4)
        self.assertAlmostEqual(decayed_boost(1.5, 3), 1.2)
        self.assertEqual(decayed_boost(1.05, 1), 1.0)
        self.assertEqual(decayed_boost(1.0, 5), 1.0)

    def test_a_boosted_topic_is_worth_more_to_the_plan(self):
        from planner.engine.types import TopicState
        base = make_plan(make_input(days_left=120, weekday=60, weekend=60, hour_scale=3))
        boosted = make_plan(make_input(days_left=120, weekday=60, weekend=60, hour_scale=3, states={5: TopicState(boost=2.0)}))
        gain = lambda r: next(t.gain for t in r.topics if t.topic_id == 5)  # noqa: E731
        self.assertAlmostEqual(gain(boosted), gain(base) * 2, places=3)


class PaceTests(SimpleTestCase):
    def test_pace_and_warning_threshold(self):
        self.assertIsNone(pace_of(0, 0))
        self.assertEqual(pace_of(60, 120), 0.5)
        self.assertTrue(pace_is_low(0.74))
        self.assertFalse(pace_is_low(config.PACE_WARNING))
        self.assertFalse(pace_is_low(None))

    def test_weak_accuracy_adds_extra_practice_only_with_enough_answers(self):
        self.assertEqual(extra_practice_minutes(4, 10, 6), config.EXTRA_PRACTICE_MIN)
        self.assertEqual(extra_practice_minutes(10, 5, 5), 0)  # exactly 50% is fine
        self.assertEqual(extra_practice_minutes(1, 3, 0), 0)  # too few answers to judge
        self.assertEqual(extra_practice_minutes(None, None, None), 0)


class RescopeTests(SimpleTestCase):
    def setUp(self):
        self.inp = make_input(days_left=120, weekday=120, weekend=180, hour_scale=2.5)
        self.result = make_plan(self.inp)
        self.included = [t.topic_id for t in sorted((t for t in self.result.topics if t.included), key=lambda t: t.sequence)]

    def test_rule_compares_need_with_what_the_student_really_gets_done(self):
        self.assertTrue(rescope_needed(100, 100, 0.5))
        self.assertFalse(rescope_needed(100, 100, 1.0))
        self.assertFalse(rescope_needed(50, 100, 0.5))
        self.assertFalse(rescope_needed(100, 100, None))

    def test_capacity_factor_scales_every_day(self):
        full = sum(d.net_minutes for d in build_days(self.inp))
        from dataclasses import replace
        half = sum(d.net_minutes for d in build_days(replace(self.inp, capacity_factor=0.5)))
        self.assertAlmostEqual(half / full, 0.5, places=1)

    def test_scenario_13_low_pace_gives_a_proposal_from_the_latest_topics(self):
        self.assertTrue(self.included)
        dropped = propose_rescope(self.inp, self.included, 0.5)
        self.assertTrue(dropped)
        self.assertTrue(set(dropped) <= set(self.included))
        position = {tid: i for i, tid in enumerate(self.included)}
        order = [position[t] for t in dropped]
        self.assertEqual(order, sorted(order, reverse=True))  # the least urgent first

    def test_scenario_13_a_good_pace_proposes_nothing(self):
        self.assertEqual(propose_rescope(self.inp, self.included, 1.0), [])
        self.assertEqual(propose_rescope(self.inp, self.included, None), [])
        self.assertEqual(propose_rescope(self.inp, self.included, 1.3), [])

    def test_scenario_13_the_dry_run_does_not_change_its_input(self):
        before = make_plan(self.inp)
        propose_rescope(self.inp, self.included, 0.4)
        self.assertEqual(before, make_plan(self.inp))

    def test_slower_pace_drops_more(self):
        mild = propose_rescope(self.inp, self.included, 0.8)
        severe = propose_rescope(self.inp, self.included, 0.3)
        self.assertGreaterEqual(len(severe), len(mild))


class CoachMessageTests(SimpleTestCase):
    WEEK = date(2027, 1, 4)

    def message(self, percent, **kwargs):
        return weekly_message(percent, self.WEEK, 7, **kwargs)

    def test_tiers_follow_the_completion_percentage(self):
        high = [self.message(p) for p in (90, 100)]
        good = [self.message(p) for p in (70, 89)]
        mid = [self.message(p) for p in (50, 69)]
        low = [self.message(p) for p in (0, 49)]
        self.assertTrue(all("%" in m for m in high + good + mid))
        self.assertTrue(all("🚀" in m for m in high))
        self.assertTrue(all("💪" in m for m in good))
        self.assertTrue(all("Sorun değil" in m or "sorun değil" in m for m in mid))
        self.assertTrue(all("🌱" in m for m in low))

    def test_percentage_is_inserted(self):
        self.assertIn("%83", self.message(83))

    def test_same_week_and_user_always_get_the_same_message(self):
        self.assertEqual(self.message(80), self.message(80))
        picks = {pick(TIERS[0][1], date.fromordinal(self.WEEK.toordinal() + i), 7) for i in range(2)}
        self.assertEqual(len(picks), len(TIERS[0][1]))  # both variants are reachable

    def test_improvement_and_focus_sentences(self):
        text = self.message(75, improved=("Paragraf", 8), focus=["Matematik", "Fizik"])
        self.assertIn("Paragraf doğruluğun %8 arttı 👏", text)
        self.assertIn("Gelecek hafta odak derslerin: Matematik, Fizik.", text)
        plain = self.message(75)
        self.assertNotIn("arttı", plain)
        self.assertNotIn("odak", plain)

    def test_tone_has_no_blame_and_no_big_promises(self):
        forbidden = ("başaramadın", "kesin kazanırsın", "garanti", "tembel")
        for _, options in TIERS:
            for option in options:
                for word in forbidden:
                    self.assertNotIn(word, option)
