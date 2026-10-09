"""Phase of the plan by days left until the exam (CLAUDE.md §6.4)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseRule:
    code: str
    name: str                    # shown to the student (Turkish)
    min_days_left: int           # phase applies when days_left >= this (and below the previous phase)
    new: float
    practice: float
    review: float
    mock_gap_days: int           # minimum days between two mocks
    mock_max_per_week: int
    mock_weekdays: tuple         # preferred weekdays, Monday = 0
    focus: str                   # plain-language focus of the phase (Turkish)


PHASES = (
    PhaseRule("P6", "Temel inşa", 151, 0.65, 0.25, 0.10, 14, 1, (5, 6),
              "Sağlam bir temel kuruyoruz: önce ön koşulu olmayan ve verimli konulardan başlıyor, yeni konuları öğreniyoruz."),
    PhaseRule("P4", "Konu bitirme", 91, 0.50, 0.35, 0.15, 10, 1, (5, 6),
              "Konuları bitiriyoruz. Soru çözme payı artıyor."),
    PhaseRule("P3", "Kapanış", 61, 0.35, 0.45, 0.20, 7, 1, (5, 6),
              "Kalan konuları kapatıyoruz. Artık daha çok soru çözeceğiz."),
    PhaseRule("P2", "Deneme dönemi", 31, 0.10, 0.55, 0.35, 3, 2, (5, 6, 2),
              "Denemeler başlıyor. Yeni konuya sadece küçük konularla devam ediyoruz; büyük konulara başlamıyoruz."),
    PhaseRule("P1", "Son ay", 8, 0.0, 0.50, 0.50, 1, 3, (5, 6, 2),
              "Yeni konu yok. Soru çözme ve tekrar; pratik denemelerde zayıf çıkan konulara odaklanıyor."),
    PhaseRule("P0", "Son hafta", 0, 0.0, 0.30, 0.70, 7, 1, (5, 6),
              "Hafif tempo: tekrar, uyku düzeni ve sınav günü hazırlığı."),
)

PHASE_BY_CODE = {rule.code: rule for rule in PHASES}
PHASE_ORDER = [rule.code for rule in PHASES]


def phase_for(days_left):
    """Return the PhaseRule for a day that is `days_left` days before the exam day."""
    for rule in PHASES:
        if days_left >= rule.min_days_left:
            return rule
    return PHASES[-1]
