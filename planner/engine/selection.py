"""Greedy scope selection with prerequisite bundles (CLAUDE.md §6.5)."""

from dataclasses import dataclass

EPS = 1e-9


@dataclass
class Selection:
    included: dict          # topic id -> reason code ("selected" / "prerequisite"), in inclusion order
    reasons: dict           # topic id -> reason code for every candidate
    sequence: list          # included topic ids in study order
    remaining: dict         # unused budgets after selection


def _sort_key(need):
    return (-need.ratio, need.topic.subject_order, need.topic.order, need.topic.id)


def _closure(topic_id, prereqs):
    """All transitive prerequisites of a topic (cycle safe)."""
    seen = set()
    stack = list(prereqs.get(topic_id, ()))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(prereqs.get(current, ()))
    return seen


def _try_spend(members, budgets):
    """Spend budgets for the members; return the new budgets or None if they do not fit."""
    new_any, new_small, practice = budgets["new_any"], budgets["new_small"], budgets["practice"]
    for need in members:
        practice -= need.practice_need
        if need.is_big:
            new_any -= need.learn_need
        else:
            from_small = min(new_small, need.learn_need)
            new_small -= from_small
            new_any -= need.learn_need - from_small
    if min(new_any, new_small, practice) < -EPS:
        return None
    return {"new_any": new_any, "new_small": new_small, "practice": practice}


def _force_spend(members, budgets):
    """Forced topics are included whatever the budget; budgets just cannot go below zero."""
    spent = _try_spend(members, budgets)
    if spent is not None:
        return spent
    spent = {"new_any": budgets["new_any"], "new_small": budgets["new_small"], "practice": budgets["practice"]}
    for need in members:
        spent["practice"] = max(0.0, spent["practice"] - need.practice_need)
        if need.is_big:
            spent["new_any"] = max(0.0, spent["new_any"] - need.learn_need)
        else:
            from_small = min(spent["new_small"], need.learn_need)
            spent["new_small"] -= from_small
            spent["new_any"] = max(0.0, spent["new_any"] - (need.learn_need - from_small))
    return spent


def select_topics(needs, budgets):
    """Pick the topics worth studying with the given budgets.

    `budgets` has the keys new_any, new_small and practice (minutes).
    """
    by_id = {n.topic.id: n for n in needs}
    prereqs = {n.topic.id: tuple(p for p in n.topic.prerequisites if p in by_id) for n in needs}
    closure = {tid: _closure(tid, prereqs) for tid in by_id}

    def required(tid):
        """Prerequisites that must be studied first: not good enough yet and not excluded by the student."""
        return [
            by_id[p] for p in closure[tid]
            if by_id[p].state.level < 2 and not by_id[p].user_excluded
        ]

    def bundle(tid, included):
        members = [by_id[tid]] if tid not in included else []
        members += [m for m in required(tid) if m.topic.id not in included]
        members.sort(key=_sort_key)
        return members

    initial = dict(budgets)
    remaining = dict(budgets)
    included = {}

    # forced topics first
    for need in sorted((n for n in needs if n.forced), key=_sort_key):
        for member in bundle(need.topic.id, included):
            remaining = _force_spend([member], remaining)
            included[member.topic.id] = "selected" if member.topic.id == need.topic.id else "prerequisite"

    pool = [n for n in needs if not n.user_excluded and n.topic.id not in included]
    while True:
        candidates = []
        for need in pool:
            if need.topic.id in included:
                continue
            members = bundle(need.topic.id, included)
            if not members:
                continue
            total_need = sum(m.need for m in members)
            total_gain = sum(m.gain for m in members)
            ratio = total_gain / total_need if total_need > 0 else 0.0
            candidates.append((-ratio, need.topic.subject_order, need.topic.order, need.topic.id, members))
        candidates.sort(key=lambda c: c[:4])

        picked = None
        for _ratio, _subject_order, _order, target, members in candidates:
            spent = _try_spend(members, remaining)
            if spent is not None:
                picked = (target, members, spent)
                break
        if picked is None:
            break
        target, members, remaining = picked
        for member in members:
            included[member.topic.id] = "selected" if member.topic.id == target else "prerequisite"

    reasons = {}
    for need in needs:
        tid = need.topic.id
        if tid in included:
            reasons[tid] = included[tid]
        elif need.user_excluded:
            reasons[tid] = "user_excluded"
        elif need.is_big and initial["new_small"] > EPS and initial["new_any"] + EPS < need.learn_need:
            reasons[tid] = "big_topic_late"
        elif need.state.level == 2:
            reasons[tid] = "already_good"
        else:
            reasons[tid] = "no_time"

    return Selection(included=included, reasons=reasons, sequence=_sequence(included, by_id, prereqs), remaining=remaining)


def _sequence(included, by_id, prereqs):
    """Topological study order; among equal depth, higher gain per minute first."""
    depth = {}

    def depth_of(tid, trail=()):
        if tid in depth:
            return depth[tid]
        if tid in trail:
            return 0
        parents = [p for p in prereqs.get(tid, ()) if p in included]
        depth[tid] = 0 if not parents else 1 + max(depth_of(p, trail + (tid,)) for p in parents)
        return depth[tid]

    ids = list(included)
    for tid in ids:
        depth_of(tid)
    ids.sort(key=lambda tid: (depth[tid],) + _sort_key(by_id[tid]))
    return ids
