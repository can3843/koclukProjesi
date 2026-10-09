"""Geometry for the hand-drawn SVG charts of the progress page. Pure functions: numbers in, coordinates out."""

from django.utils.formats import number_format

WIDTH = 480
HEIGHT = 270
MARGIN = {"left": 50, "right": 14, "top": 24, "bottom": 40}
NICE_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000)
MAX_TICKS = 5
MAX_X_LABELS = 5


def _plot():
    return (
        MARGIN["left"], MARGIN["top"],
        WIDTH - MARGIN["right"], HEIGHT - MARGIN["bottom"],
    )


def _nice_step(span):
    for step in NICE_STEPS:
        if span / step <= MAX_TICKS:
            return step
    return NICE_STEPS[-1]


def _scale(low, high, cap=None):
    """(axis min, axis max, step): round numbers around the data, never above `cap`."""
    low, high = min(low, 0), max(high, 1)
    step = _nice_step(high - low)
    axis_min = step * (low // step)
    axis_max = step * (-(-high // step))
    if cap is not None and axis_max > cap:
        axis_max = max(cap, high)
    return axis_min, axis_max, step


def fmt(value, places=2):
    """Number with the Turkish decimal comma (18,25)."""
    return number_format(value, decimal_pos=places, use_l10n=True)


def _ticks(axis_min, axis_max, step, y_of):
    ticks, value = [], axis_min
    while value <= axis_max + 1e-9:
        ticks.append({"y": round(y_of(value), 1), "label": number_format(value, decimal_pos=0, use_l10n=True)})
        value += step
    return ticks


def _label_indices(count):
    """Indices that get an x label: evenly spread, always including the newest point."""
    every = max(1, -(-count // MAX_X_LABELS))
    return {i for i in range(count) if (count - 1 - i) % every == 0}


def _x_labels(labels, x_of):
    shown = _label_indices(len(labels))
    return [{"x": round(x_of(i), 1), "label": label} for i, label in enumerate(labels) if i in shown]


def line_chart(points, cap=None, goal=None):
    """Net-over-time line. `points`: [{"label": "12 Oca", "value": float, "title": str}], oldest first.

    `cap` is the highest possible value (question count); `goal` an optional target drawn as a dashed line.
    """
    left, top, right, bottom = _plot()
    values = [p["value"] for p in points]
    top_value = max(values + ([goal] if goal is not None else []))
    axis_min, axis_max, step = _scale(min(values), top_value * 1.08, cap)
    span = (axis_max - axis_min) or 1

    def y_of(value):
        return bottom - (value - axis_min) / span * (bottom - top)

    count = len(points)

    def x_of(index):
        if count == 1:
            return (left + right) / 2
        return left + index * (right - left) / (count - 1)

    dots = [
        {
            "x": round(x_of(i), 1), "y": round(y_of(p["value"]), 1),
            "value": fmt(p["value"]), "title": p["title"], "last": i == count - 1,
        }
        for i, p in enumerate(points)
    ]
    path = " ".join(f"{'M' if i == 0 else 'L'}{d['x']} {d['y']}" for i, d in enumerate(dots))
    return {
        "width": WIDTH, "height": HEIGHT, "left": left, "right": right, "bottom": bottom,
        "dots": dots, "path": path,
        "yticks": _ticks(axis_min, axis_max, step, y_of),
        "xlabels": _x_labels([p["label"] for p in points], x_of),
        "goal": None if goal is None else {"y": round(y_of(goal), 1), "label": fmt(goal)},
    }


def _bar_path(x, y, width, height, radius=4):
    """A bar standing on the baseline with only its top corners rounded."""
    radius = min(radius, width / 2, height)
    return (
        f"M{x} {y + height} V{y + radius} Q{x} {y} {x + radius} {y} "
        f"H{x + width - radius} Q{x + width} {y} {x + width} {y + radius} V{y + height} Z"
    )


def bar_chart(bars):
    """Study hours per week. `bars`: [{"label", "done", "planned" (hours), "title"}]; done sits in front of planned."""
    left, top, right, bottom = _plot()
    highest = max([b["planned"] for b in bars] + [b["done"] for b in bars] + [1])
    axis_min, axis_max, step = _scale(0, highest * 1.05)
    span = (axis_max - axis_min) or 1

    def y_of(value):
        return bottom - value / span * (bottom - top)

    shown = _label_indices(len(bars))
    slot = (right - left) / len(bars)
    bar_width = min(44, slot * 0.62)
    out = []
    for i, bar in enumerate(bars):
        x = round(left + slot * i + (slot - bar_width) / 2, 1)
        planned_y, done_y = y_of(bar["planned"]), y_of(bar["done"])
        out.append({
            "label": bar["label"], "title": bar["title"],
            "cx": round(x + bar_width / 2, 1),
            "planned_path": _bar_path(x, round(planned_y, 1), round(bar_width, 1), round(bottom - planned_y, 1)) if bar["planned"] else "",
            "done_path": _bar_path(x, round(done_y, 1), round(bar_width, 1), round(bottom - done_y, 1)) if bar["done"] else "",
            "value_y": round(min(done_y, planned_y) - 6, 1),
            "done": bar["done"], "value_label": fmt(bar["done"], 1), "show_label": i in shown,
        })
    return {
        "width": WIDTH, "height": HEIGHT, "left": left, "right": right, "bottom": bottom,
        "bars": out,
        "yticks": [{**t, "label": f"{t['label']} sa"} for t in _ticks(axis_min, axis_max, step, y_of)],
    }
