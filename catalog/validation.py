"""Exam data validation rules (CLAUDE.md §5.2), shared by `check_exam_data`, `seed_exam_data` and the admin."""

from dataclasses import dataclass, field
from decimal import Decimal

from .models import ExamTest, Subject, Topic

QUESTION_TOLERANCE = Decimal("0.5")


@dataclass
class ValidationReport:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    estimated_topics: int = 0
    total_topics: int = 0

    @property
    def ok(self):
        return not self.errors


def find_cycle(graph):
    """Return one dependency cycle as a list of nodes, or None. `graph` maps node -> iterable of prerequisites."""
    WHITE, GREY, BLACK = 0, 1, 2
    state = {}
    for start in graph:
        if state.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(graph.get(start, ())))]
        path = [start]
        state[start] = GREY
        while stack:
            node, children = stack[-1]
            for child in children:
                if state.get(child, WHITE) == GREY:
                    return path[path.index(child):] + [child]
                if state.get(child, WHITE) == WHITE:
                    state[child] = GREY
                    path.append(child)
                    stack.append((child, iter(graph.get(child, ()))))
                    break
            else:
                state[node] = BLACK
                path.pop()
                stack.pop()
    return None


def validate_catalog(exam=None):
    """Check the catalog (optionally a single exam) and return a ValidationReport."""
    report = ValidationReport()

    tests = ExamTest.objects.select_related("session__exam").prefetch_related("subjects")
    subjects = Subject.objects.select_related("test__session__exam").prefetch_related("topics")
    topics = Topic.objects.select_related("subject__test__session").prefetch_related("prerequisites")
    if exam is not None:
        tests = tests.filter(session__exam=exam)
        subjects = subjects.filter(test__session__exam=exam)
        topics = topics.filter(subject__test__session__exam=exam)

    for test in tests:
        total = sum(s.question_count for s in test.subjects.all())
        if total != test.question_count:
            report.errors.append(
                f"Test '{test.slug}': derslerin soru toplamı {total}, testin soru sayısı {test.question_count}."
            )

    for subject in subjects:
        total = sum((t.avg_questions for t in subject.topics.all()), Decimal("0"))
        if abs(total - subject.question_count) > QUESTION_TOLERANCE:
            report.warnings.append(
                f"Ders '{subject.slug}': konuların ortalama soru toplamı {total}, dersin soru sayısı {subject.question_count}."
            )

    graph = {}
    for topic in topics:
        report.total_topics += 1
        if topic.is_estimated:
            report.estimated_topics += 1
        if topic.learn_hours <= 0:
            report.errors.append(f"Konu '{topic.slug}': öğrenme süresi 0'dan büyük olmalı.")
        if topic.avg_questions < 0:
            report.errors.append(f"Konu '{topic.slug}': ortalama soru sayısı negatif olamaz.")
        exam_id = topic.subject.test.session.exam_id
        prereq_ids = []
        for prereq in topic.prerequisites.all():
            if prereq.pk == topic.pk:
                report.errors.append(f"Konu '{topic.slug}': kendi kendisinin ön koşulu olamaz.")
                continue
            if prereq.subject.test.session.exam_id != exam_id:
                report.errors.append(f"Konu '{topic.slug}': ön koşul '{prereq.slug}' başka bir sınava ait.")
                continue
            prereq_ids.append(prereq.slug)
        graph[topic.slug] = prereq_ids

    cycle = find_cycle(graph)
    if cycle:
        report.errors.append("Ön koşullarda döngü var: " + " → ".join(cycle))

    return report
