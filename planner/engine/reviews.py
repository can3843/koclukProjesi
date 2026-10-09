"""Spaced repetition rules: 1, 7, 30 days after learning a topic (CLAUDE.md §6.7)."""

from datetime import timedelta

from . import config


def first_review(learned_on, exam_date):
    """(interval_index, due_date) of the first review, or None if it would fall on/after exam day."""
    due = learned_on + timedelta(days=config.REVIEW_INTERVALS_DAYS[0])
    if due >= exam_date:
        return None
    return 0, due


def accuracy_of(correct, wrong, blank):
    """Share of correct answers among the entered ones; None if nothing was entered."""
    total = (correct or 0) + (wrong or 0) + (blank or 0)
    if total == 0:
        return None
    return (correct or 0) / total


def after_review(interval_index, accuracy, done_on, exam_date):
    """State of a review item after one review was done.

    Returns (is_active, interval_index, due_date). A weak result repeats the same interval after
    REVIEW_RETRY_DAYS; a good (or unknown) result moves on to the next interval; the last interval
    finishes the item. Nothing is planned for exam day or later.
    """
    failed = accuracy is not None and accuracy < config.REVIEW_FAIL_ACCURACY
    if failed:
        index, due = interval_index, done_on + timedelta(days=config.REVIEW_RETRY_DAYS)
    else:
        index = interval_index + 1
        if index >= len(config.REVIEW_INTERVALS_DAYS):
            return False, interval_index, done_on
        due = done_on + timedelta(days=config.REVIEW_INTERVALS_DAYS[index])
    if due >= exam_date:
        return False, index, due
    return True, index, due
