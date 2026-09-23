ENGINE_VERSION = "1.1.0"
RANDOM_SEED = 42

SEED_MIX_MIN_KZT = 50_000

COORD_MIN_PAYERS = 5
COORD_MIN_RECIPIENTS = 10
COORD_ALT_PAYERS = 3
COORD_ALT_SEED_SOURCES = 3
COORD_ALT_MIN_RECIPIENTS = 2
COORD_LINK_SEED_SOURCES = 2
COORD_LINK_BETWEENNESS = 0.90
COORD_LINK_PARTNER_CLUSTERS = 3

CONS_MIN_PAYERS = 5
CONS_ALT_PAYERS = 3
CONS_ALT_SEED_SOURCES = 3
CONS_FUNNEL_BASE = 2
CONS_FUNNEL_FACTOR = 3
CONS_RETAIN_MAX_RATIO = 0.8

DIST_MIN_RECIPIENTS = 10
DIST_FANOUT_FACTOR = 2

TRANSIT_RATIO = (0.5, 1.5)
FAST_DAYS = 2
FAST_MIN_SHARE = 0.5
# Timestamps are daily, so a same-day in/out pair may be ordered either way; transit also needs a
# share that provably left 1–2 days after arriving.
STRICT_FAST_MIN_SHARE = 0.25

TERMINAL_MAX_RATIO = 0.2
# Money received in the last days of the window may still leave after it ends.
TERMINAL_MIN_FOLLOWUP_DAYS = 7

SYNC_MIN_PAYERS = 3
BURST_MIN_TX = 5
BURST_MIN_SHARE = 0.5
SPLIT_MIN_TX = 3
SMALL_MIN_TX = 5
SMALL_MIN_SHARE = 0.5
REPEATED_ROUTE_MIN_DAYS = 2
CYCLE_MAX_LENGTH = 3
CYCLE_RETURN_DAYS = 7
HOP_ANOMALY_MIN_Z = 3.5
ROBUST_SCALE_FLOOR = 0.25
BOTTLENECK_MIN_NODES = 20
BETWEENNESS_SAMPLES = 128
LIKELY_CONTINUES_P = 0.5
TRUNCATION_MODEL_MIN_TRAIN = 30
TRUNCATION_MODEL_MIN_CLASS = 5
TRANSFER_CHECK_MIN_NODES = 20

LOUVAIN_RESOLUTION = 1.0

PRIORITY_WEIGHTS = {
    "money": 0.15,
    "converge": 0.15,
    "control": 0.15,
    "collect": 0.10,
    "volume": 0.10,
    "bridge": 0.10,
    "role": 0.15,
    "signals": 0.10,
}
ROLE_WEIGHT = {
    "coordinator": 1.0,
    "consolidator": 1.0,
    "distributor": 0.8,
    "transit": 0.7,
    "terminal": 0.35,
    "peripheral": 0.1,
}
RED_FLAGS = (
    "fast_transit",
    "sync_inflow",
    "burst",
    "structuring",
    "small_amounts",
    "dated_return",
    "repeated_route",
    "hop_anomaly",
)
# Seeds are already known to law enforcement; the analyst's attention should shift to new participants.
SEED_PRIORITY_FACTOR = 0.85
TRUNCATED_PRIORITY_FACTOR = 0.75
ISOLATED_PRIORITY_FACTOR = 0.0
TOP_N = 50

RESILIENCE_N = (5, 10, 20, 50)
RESILIENCE_RANDOM_TRIALS = 20

ROLES = ("coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral")
