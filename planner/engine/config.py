"""All tunable numbers of the plan engine live here (CLAUDE.md §6.2). No magic numbers elsewhere."""

BUFFER_RATIO = 0.15            # share of capacity kept for unexpected days

# Need by level: learn_hours * 60 * NEED_FACTOR
NEED_FACTOR = {0: 1.00, 1: 0.55, 2: 0.20}
# Share of the need spent on learning (the rest is question practice)
LEARN_SHARE = {0: 0.40, 1: 0.20, 2: 0.00}

# Estimated success rate by level (share of the topic's questions that become net)
CURRENT_RATE = {0: 0.10, 1: 0.40, 2: 0.75}
TARGET_RATE = 0.80             # expected rate when the topic is finished as planned
MAX_RATE = 0.92
MIN_MEASURED_QUESTIONS = 20    # solved questions needed before measured accuracy is trusted

BIG_TOPIC_HOURS = 6            # topics needing more learning hours than this are "big"

LEARN_BLOCK_MIN = 45
PRACTICE_BLOCK_MIN = 40
REVIEW_TASK_MIN = 20
MIN_BLOCK_MIN = 20
MOCK_ANALYSIS_MIN = 60

MAX_ACTIVE_TOPICS = 3
MAX_SAME_SUBJECT_BLOCKS_PER_DAY = 2

REVIEW_INTERVALS_DAYS = [1, 7, 30]
REVIEW_FAIL_ACCURACY = 0.60
REVIEW_RETRY_DAYS = 3

PRACTICE_WEAK_ACCURACY = 0.50
EXTRA_PRACTICE_MIN = 40

BOOST_STEP = 0.25
BOOST_MAX = 2.0
BOOST_DECAY_PER_WEEK = 0.10

PACE_WARNING = 0.75
RESCOPE_TOLERANCE = 1.05

PROJECTION_LOW = 0.85
PROJECTION_HIGH = 1.05
MOCK_CALIBRATION_BOUNDS = (0.70, 1.30)
CALIBRATION_MOCK_COUNT = 2     # latest mocks averaged per subject
PACE_MIN_PLAN_AGE_DAYS = 14    # pace correction starts this many days after the plan was made

WINDOW_DAYS = 7
LAST_DAY_MAX_MIN = 60
FINAL_WEEK_CAPACITY_FACTOR = 0.60

# ---- Added for the capacity / mock calendar (not listed in §6.2 but needed by §6.3-6.4) ----
CAPACITY_ROUNDING_MIN = 5      # net daily capacity is rounded to this many minutes
EXTRA_HOUR_SCENARIO_MIN = 60   # "if you study 1 more hour a day" scenario
MOCK_FREE_LAST_DAYS = 3        # no mock in the last N days before the exam
EARLY_TYT_ONLY_DAYS = 30       # P6: only the first session is mocked this long when advanced topics are untouched
EARLY_TYT_ONLY_LEVEL0_SHARE = 0.70

# ---- Added for Phase 5 (adaptation) ----
WEAK_PRACTICE_MIN_ANSWERED = 5     # answered questions needed before a low accuracy adds extra practice
PACE_WINDOW_DAYS = 14              # pace = done / planned minutes over the last N days (today excluded)
PACE_MIN_PLANNED_DAYS = 3          # days with planned tasks needed before pace is trusted
RESCOPE_SNOOZE_DAYS = 7            # "not now" hides the scope suggestion for this many days
IMPROVEMENT_MIN_ANSWERED = 10      # answered questions needed in both weeks to report an improvement
FOCUS_SUBJECT_COUNT = 3            # next week's focus subjects in the weekly review
