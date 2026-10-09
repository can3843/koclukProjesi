"""Need (minutes) and gain (expected net questions) per topic (CLAUDE.md §6.5)."""

from dataclasses import dataclass

from . import config
from .types import TopicInfo, TopicState


@dataclass(frozen=True)
class Need:
    topic: TopicInfo
    state: TopicState
    learn_need: float
    practice_need: float
    gain: float
    is_big: bool
    user_excluded: bool
    forced: bool

    @property
    def need(self):
        return self.learn_need + self.practice_need

    @property
    def ratio(self):
        return self.gain / self.need if self.need > 0 else 0.0


def measured_net_rate(state):
    """Measured net rate from solved questions, or None until enough questions were solved."""
    if state.solved < config.MIN_MEASURED_QUESTIONS:
        return None
    rate = (state.correct - state.wrong / 4) / state.solved
    return min(1.0, max(0.0, rate))


def current_rate(state):
    base = config.CURRENT_RATE[state.level]
    measured = measured_net_rate(state)
    return base if measured is None else (base + measured) / 2


def exam_day_rate(state):
    """Expected rate on exam day if the topic is finished as planned."""
    measured = measured_net_rate(state)
    return config.TARGET_RATE if measured is None else min(config.MAX_RATE, measured)


def build_need(topic, state):
    level = state.level
    if state.state == "in_progress" and state.remaining_learn is not None and state.remaining_practice is not None:
        learn_need = float(state.remaining_learn)
        practice_need = float(state.remaining_practice)
    else:
        need = topic.learn_hours * 60 * config.NEED_FACTOR[level]
        learn_need = need * config.LEARN_SHARE[level]
        practice_need = need - learn_need
    gain = topic.avg_questions * max(0.0, config.TARGET_RATE - current_rate(state)) * state.boost
    forced = state.override == "force_include"
    user_excluded = not forced and (state.override == "force_exclude" or state.state == "excluded")
    return Need(
        topic=topic,
        state=state,
        learn_need=learn_need,
        practice_need=practice_need,
        gain=gain,
        is_big=topic.learn_hours > config.BIG_TOPIC_HOURS,
        user_excluded=user_excluded,
        forced=forced,
    )


def candidate_needs(inp):
    """Needs of every topic that still has to be studied (learned topics are not candidates)."""
    needs = []
    for topic in inp.topics:
        state = inp.states.get(topic.id) or TopicState()
        if state.state == "learned":
            continue
        needs.append(build_need(topic, state))
    return needs
