"""Plain data classes exchanged with the engine. The engine never touches the database."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class SessionInfo:
    code: str                    # TYT, AYT, YDT
    date: date
    duration_minutes: int


@dataclass(frozen=True)
class TestInfo:
    slug: str
    name: str
    session_code: str
    question_count: int


@dataclass(frozen=True)
class SubjectInfo:
    id: int
    name: str
    test_slug: str
    order: int
    question_count: int


@dataclass(frozen=True)
class TopicInfo:
    id: int
    subject_id: int
    subject_order: int
    order: int
    name: str
    avg_questions: float
    learn_hours: float
    difficulty: int = 2
    prerequisites: tuple = ()    # topic ids


@dataclass(frozen=True)
class TopicState:
    level: int = 0               # 0 / 1 / 2
    state: str = "not_started"   # not_started, in_progress, learned, excluded
    remaining_learn: Optional[float] = None
    remaining_practice: Optional[float] = None
    boost: float = 1.0
    solved: int = 0
    correct: int = 0
    wrong: int = 0
    override: Optional[str] = None   # None, force_include, force_exclude


@dataclass(frozen=True)
class MockResult:
    """Net score per subject id of one finished mock exam."""
    nets: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PlanInput:
    today: date
    sessions: tuple                  # SessionInfo, ordered; the first one is exam day
    session_codes: tuple             # sessions that belong to the student's track, in mock order
    tests: tuple                     # TestInfo (only the track's tests)
    subjects: tuple                  # SubjectInfo
    topics: tuple                    # TopicInfo (active topics of the track)
    states: dict                     # topic id -> TopicState (missing = default)
    weekday_minutes: int
    weekend_minutes: int
    rest_weekday: Optional[int] = None
    mocks: tuple = ()                # MockResult, most recent first
    pace: Optional[float] = None
    plan_age_days: int = 0
    extra_minutes_per_day: int = 0   # for the "+1 hour a day" scenario
    known_mock_dates: tuple = ()     # dates of mocks already taken, missed or still planned (keeps the calendar stable)
    capacity_factor: float = 1.0     # share of the stated capacity the student really delivers (scope dry-run)


@dataclass(frozen=True)
class DayPlan:
    date: date
    days_left: int
    phase_code: str
    raw_minutes: float
    net_minutes: float
    is_rest: bool
    mock_session: Optional[str]
    mock_minutes: float              # mock duration + analysis planned on this day
    new_any: float
    new_small: float
    practice: float
    review: float
    mock_duration: float = 0.0       # minutes of the mock exam itself
    analysis_minutes: float = 0.0    # minutes of mock analysis scheduled on this day (own or carried over)


@dataclass(frozen=True)
class Budget:
    raw_total: int
    mock_minutes: int
    new_any: int
    new_small: int
    practice: int
    review: int

    @property
    def new_total(self):
        return self.new_any + self.new_small

    @property
    def study_total(self):
        """Minutes available for learning new topics and question practice."""
        return self.new_any + self.new_small + self.practice


@dataclass(frozen=True)
class TopicResult:
    topic_id: int
    included: bool
    sequence: Optional[int]
    priority: float
    gain: float
    need_minutes: int
    reason_code: str                 # selected, already_good, no_time, big_topic_late, user_excluded, prerequisite
    start_day: Optional[int] = None  # rough day offset (from today) when learning starts


@dataclass(frozen=True)
class TestProjection:
    test_slug: str
    name: str
    session_code: str
    question_count: int
    now: int
    low: int
    high: int


@dataclass(frozen=True)
class SessionProjection:
    code: str
    question_count: int
    now: int
    low: int
    high: int


@dataclass(frozen=True)
class ProjectionResult:
    tests: tuple
    sessions: tuple


@dataclass(frozen=True)
class PlanResult:
    phase_code: str
    days_left: int
    exam_date: date
    budget: Budget
    required_minutes: int
    coverage_ratio: float
    fits_all: bool
    topics: tuple                    # TopicResult, in input order
    projection: ProjectionResult
    plus_hour_projection: Optional[ProjectionResult] = None
    mock_count: int = 0
