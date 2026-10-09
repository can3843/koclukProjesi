"""Day by day task scheduler (CLAUDE.md §6.7). Pure Python: budgets and topic states in, tasks out.

The scheduler simulates progress while it plans, so a topic whose learning is planned on Monday can be
practiced on Tuesday. Days that already have tasks ("committed") are not regenerated; their pending
tasks only count as progress.
"""

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import config

MOCK_NOTE = "Bu deneme için o gün biraz daha fazla zaman ayırmaya çalış."


@dataclass(frozen=True)
class ScheduleTopic:
    id: int
    name: str
    subject_id: int
    subject_name: str
    group: str
    difficulty: int
    is_big: bool
    minutes_per_question: float
    prerequisites: tuple = ()
    learn_remaining: float = 0.0
    practice_remaining: float = 0.0
    started: bool = False
    level: int = 0


@dataclass(frozen=True)
class ReviewDue:
    item_id: int
    topic_id: int
    due_date: date


@dataclass(frozen=True)
class PlannedTask:
    date: date
    kind: str                        # learn, practice, review, mock, mock_review
    topic_id: Optional[int]
    subject_id: Optional[int]
    session_code: Optional[str]
    title: str
    minutes: int
    question_target: Optional[int]
    order: int
    is_peak: bool
    review_item_id: Optional[int] = None
    note: str = ""


def question_target(minutes, minutes_per_question):
    """Practice question count: minutes / minutes-per-question, rounded to 5, at least 10."""
    raw = minutes / minutes_per_question if minutes_per_question else minutes
    return max(10, int(raw / 5.0 + 0.5) * 5)  # nearest 5, halves go up


def _ceil(value):
    return int(math.ceil(value - 1e-9)) if value > 0 else 0


def _arrange(items, previous_subject):
    """Order items (kept in priority order) so that equal subjects are not neighbours when avoidable."""
    remaining = list(items)
    result = []
    prev = previous_subject
    while remaining:
        counts = Counter(i["subject_id"] for i in remaining)
        total = len(remaining)
        crowded = [s for s, c in counts.items() if c * 2 > total and s is not None]
        pick = None
        if crowded and crowded[0] != prev:
            pick = next(i for i in remaining if i["subject_id"] == crowded[0])
        if pick is None:
            pick = next((i for i in remaining if i["subject_id"] != prev or i["subject_id"] is None), remaining[0])
        remaining.remove(pick)
        result.append(pick)
        prev = pick["subject_id"]
    return result


class _Scheduler:
    def __init__(self, topics, sequence, fallback_ids, reviews):
        self.topics = topics
        self.sequence = [tid for tid in sequence if tid in topics]
        self.seq_index = {tid: i for i, tid in enumerate(self.sequence)}
        self.fallback_ids = [tid for tid in fallback_ids if tid in topics]
        self.reviews = list(reviews)
        self.learn = {t.id: _ceil(t.learn_remaining) for t in topics.values()}
        self.practice = {t.id: _ceil(t.practice_remaining) for t in topics.values()}
        self.started = {t.id for t in topics.values() if t.started}
        self.unfinished = {tid for tid in self.sequence if self.learn[tid] > 0 or self.practice[tid] > 0}
        self.active = [tid for tid in self.sequence if tid in self.unfinished and tid in self.started][: config.MAX_ACTIVE_TOPICS]
        self.used_reviews = set()
        self.review_bank = 0.0
        self.tasks = []

    # ---- state helpers -------------------------------------------------
    def _prereqs_met(self, topic):
        return not any(
            p in self.unfinished and self.topics[p].level < 2 for p in topic.prerequisites if p in self.topics
        )

    def _finish_if_done(self, tid):
        if self.learn[tid] <= 0 and self.practice[tid] <= 0:
            self.unfinished.discard(tid)
            if tid in self.active:
                self.active.remove(tid)

    def apply_committed(self, items):
        for topic_id, kind, minutes, item_id in items:
            if kind == "review" and item_id is not None:
                self.used_reviews.add(item_id)
            if topic_id not in self.topics:
                continue
            if kind == "learn":
                self.learn[topic_id] = max(0, self.learn[topic_id] - minutes)
                self.started.add(topic_id)
            elif kind == "practice" and topic_id in self.unfinished:
                self.practice[topic_id] = max(0, self.practice[topic_id] - minutes)
                self.started.add(topic_id)
            self._finish_if_done(topic_id)

    def ensure_active(self, day_phase, allow_learn_start):
        self.active = [t for t in self.active if t in self.unfinished]
        while len(self.active) < config.MAX_ACTIVE_TOPICS:
            groups = {self.topics[a].group for a in self.active}
            eligible = []
            for tid in self.sequence:
                if tid in self.active or tid not in self.unfinished:
                    continue
                topic = self.topics[tid]
                if not self._prereqs_met(topic):
                    continue
                if self.learn[tid] > 0:
                    if not allow_learn_start:
                        continue
                    if topic.is_big and day_phase == "P2" and tid not in self.started:
                        continue  # no big topic is started in the deneme period
                eligible.append(tid)
            if not eligible:
                break
            pick = next((tid for tid in eligible if self.topics[tid].group not in groups), eligible[0])
            self.active.append(pick)
        self.active.sort(key=self.seq_index.get)

    # ---- block builders --------------------------------------------------
    def _add(self, day, items, kind, topic, minutes, per_subject, **extra):
        per_subject[topic.subject_id] += 1
        if kind == "learn":
            title = f"{topic.subject_name} – {topic.name}: {minutes} dk konu çalışması"
            target = None
        elif kind == "practice":
            target = question_target(minutes, topic.minutes_per_question)
            title = f"{topic.subject_name} – {topic.name}: {target} soru"
        else:  # review
            target = question_target(minutes, topic.minutes_per_question)
            title = f"Tekrar: {topic.name} – {target} soru"
        peak = kind == "learn" or topic.difficulty >= 3
        items.append({
            "kind": kind, "topic_id": topic.id, "subject_id": topic.subject_id, "session_code": None,
            "title": title, "minutes": minutes, "question_target": target, "is_peak": peak, **extra,
        })

    def fill_learn(self, day, items, budget, per_subject):
        while budget >= config.MIN_BLOCK_MIN:
            progressed = False
            for tid in list(self.active):
                if self.learn[tid] <= 0 or per_subject[self.topics[tid].subject_id] >= config.MAX_SAME_SUBJECT_BLOCKS_PER_DAY:
                    continue
                remaining = self.learn[tid]
                block = min(config.LEARN_BLOCK_MIN, remaining)
                if remaining - block < config.MIN_BLOCK_MIN:
                    block = remaining  # absorb a short tail
                block = min(block, int(budget))
                if block <= 0 or (block < config.MIN_BLOCK_MIN and block < remaining):
                    continue
                self._add(day, items, "learn", self.topics[tid], block, per_subject)
                self.learn[tid] -= block
                self.started.add(tid)
                budget -= block
                progressed = True
                self._finish_if_done(tid)
                if budget < config.MIN_BLOCK_MIN:
                    break
            if not progressed:
                break
        return budget

    def _practice_candidates(self):
        """(topic id, tied to remaining practice) in priority order, §6.7 step 6."""
        tied = [tid for tid in self.active if self.learn[tid] <= 0 and self.practice[tid] > 0]
        extra = [tid for tid in self.fallback_ids if tid not in tied]
        return [(tid, True) for tid in tied] + [(tid, False) for tid in extra]

    def fill_practice(self, day, items, budget, per_subject):
        used = set()
        while budget >= config.MIN_BLOCK_MIN:
            progressed = False
            for tid, tied in self._practice_candidates():
                topic = self.topics[tid]
                if per_subject[topic.subject_id] >= config.MAX_SAME_SUBJECT_BLOCKS_PER_DAY:
                    continue
                if not tied and tid in used:
                    continue
                if tied:
                    remaining = self.practice[tid]
                    block = min(config.PRACTICE_BLOCK_MIN, remaining)
                    if remaining - block < config.MIN_BLOCK_MIN:
                        block = remaining
                else:
                    block = config.PRACTICE_BLOCK_MIN
                block = min(block, int(budget))
                if block < config.MIN_BLOCK_MIN and not (tied and block == self.practice[tid]):
                    continue
                if block <= 0:
                    continue
                self._add(day, items, "practice", topic, block, per_subject)
                budget -= block
                used.add(tid)
                progressed = True
                if tied:
                    self.practice[tid] -= block
                    self.started.add(tid)
                    self._finish_if_done(tid)
                if budget < config.MIN_BLOCK_MIN:
                    break
            if not progressed:
                break
        return budget

    # ---- one day ---------------------------------------------------------
    def plan_day(self, day):
        items = []
        per_subject = Counter()
        mock_items, review_items = [], []

        if day.mock_session:
            minutes = int(round(day.mock_duration))
            note = MOCK_NOTE if day.net_minutes < day.mock_duration else ""
            mock_items.append({
                "kind": "mock", "topic_id": None, "subject_id": None, "session_code": day.mock_session,
                "title": f"{day.mock_session} Denemesi – {minutes} dk, gerçek sınav gibi süre tut",
                "minutes": minutes, "question_target": None, "is_peak": True, "note": note,
            })
        if day.analysis_minutes >= 1:
            minutes = int(round(day.analysis_minutes))
            review_items.append({
                "kind": "mock_review", "topic_id": None, "subject_id": None, "session_code": None,
                "title": f"Deneme analizi: yanlışlarını incele – {minutes} dk",
                "minutes": minutes, "question_target": None, "is_peak": False,
            })

        learn_budget = day.new_any + day.new_small
        practice_budget = day.practice

        # 1. due reviews, oldest first. They are paid from the review budget first; when that is too small
        #    (e.g. 10% of a short day) they borrow from practice and then new-topic time, so they come on time.
        bank = self.review_bank + day.review
        study_total = learn_budget + practice_budget + bank
        cap = max(bank, 0.5 * study_total)  # reviews never take more than half of the day's study time
        spent = 0.0
        due = sorted(
            (r for r in self.reviews if r.due_date <= day.date and r.item_id not in self.used_reviews and r.topic_id in self.topics),
            key=lambda r: (r.due_date, r.item_id),
        )
        review_task_items = []
        for review in due:
            topic = self.topics[review.topic_id]
            if per_subject[topic.subject_id] >= config.MAX_SAME_SUBJECT_BLOCKS_PER_DAY:
                continue
            cost = config.REVIEW_TASK_MIN
            if spent + cost > cap + 1e-9 or bank + practice_budget + learn_budget < cost - 1e-9:
                break
            from_bank = min(bank, cost)
            bank -= from_bank
            rest = cost - from_bank
            from_practice = min(practice_budget, rest)
            practice_budget -= from_practice
            learn_budget -= rest - from_practice
            spent += cost
            self._add(day, review_task_items, "review", topic, config.REVIEW_TASK_MIN, per_subject,
                      review_item_id=review.item_id)
            self.used_reviews.add(review.item_id)
        self.review_bank = bank
        if not any(r.item_id not in self.used_reviews for r in due):
            practice_budget += self.review_bank  # nothing left to review: the time goes to practice
            self.review_bank = 0.0

        # 2. active topics, new learning, practice (unused new-topic time goes to practice and back)
        self.ensure_active(day.phase_code, allow_learn_start=learn_budget >= config.MIN_BLOCK_MIN)
        study_items = []
        learn_budget = self.fill_learn(day, study_items, learn_budget, per_subject)
        practice_budget += learn_budget
        practice_budget = self.fill_practice(day, study_items, practice_budget, per_subject)
        if practice_budget >= config.MIN_BLOCK_MIN:
            self.ensure_active(day.phase_code, allow_learn_start=True)
            self.fill_learn(day, study_items, practice_budget, per_subject)

        # 3. order: mock first, peak-time work next, mixed subjects, mock analysis last
        pool = review_task_items + study_items
        peak = [i for i in pool if i["is_peak"]]
        rest = [i for i in pool if not i["is_peak"]]
        # one pass over peak-time work first, then the rest: equal subjects are never neighbours when avoidable
        ordered = mock_items + _arrange(peak + rest, None) + review_items

        for index, item in enumerate(ordered, start=1):
            self.tasks.append(PlannedTask(
                date=day.date,
                kind=item["kind"],
                topic_id=item["topic_id"],
                subject_id=item["subject_id"],
                session_code=item["session_code"],
                title=item["title"],
                minutes=item["minutes"],
                question_target=item["question_target"],
                order=index,
                is_peak=item["is_peak"],
                review_item_id=item.get("review_item_id"),
                note=item.get("note", ""),
            ))


def schedule(days, topics, sequence, fallback_ids=(), reviews=(), committed=None):
    """Plan tasks for `days` (DayPlan list, in order).

    topics:    id -> ScheduleTopic for every topic that can appear (plan topics, review topics, fallbacks)
    sequence:  included topic ids in study order
    committed: date -> iterable of (topic_id, kind, minutes, review_item_id) of tasks that already exist
    """
    committed = committed or {}
    scheduler = _Scheduler(topics, sequence, fallback_ids, reviews)
    for day in days:
        if day.date in committed:
            scheduler.apply_committed(committed[day.date])
            continue
        if day.is_rest or day.net_minutes <= 0:
            continue
        scheduler.plan_day(day)
    return tuple(scheduler.tasks)
