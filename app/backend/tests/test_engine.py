import pandas as pd
import pytest

from moneygraph.collection import Collection
from moneygraph.data import DataValidationError, infer_collection, validate_inputs
from moneygraph.pipeline import CollectionOverrides, run

from .datasets import (
    CONSOLIDATOR,
    DISTRIBUTOR,
    FAN_OUT,
    ISOLATED_SEED,
    LAST_HOP,
    TERMINAL,
    TRANSIT,
    build_frames,
    crafted_frames,
    write_dataset,
)

JULY = CollectionOverrides(
    max_depth=4, observation_start="2026-07-01", observation_end="2026-07-31", min_transfer_kzt=5000.0
)


@pytest.fixture
def crafted_run(tmp_path):
    data_dir = write_dataset(tmp_path / "input", *crafted_frames())
    stats = run(data_dir, tmp_path / "out", tmp_path / "api", JULY)
    roles = pd.read_csv(tmp_path / "out" / "nodes_roles.csv").set_index("gid")
    return stats, roles


def test_each_rule_assigns_its_role(crafted_run):
    _, roles = crafted_run
    assert roles.role[CONSOLIDATOR] == "consolidator"
    assert roles.role[DISTRIBUTOR] == "distributor"
    assert roles.role[TRANSIT] == "transit"
    assert roles.role[TERMINAL] == "terminal"
    assert roles.role[FAN_OUT[1]] == "terminal"


def test_last_hop_is_never_terminal(crafted_run):
    _, roles = crafted_run
    assert roles.role[LAST_HOP] == "peripheral"
    assert "truncated" in roles["flags"][LAST_HOP]


def test_isolated_seed_is_peripheral_and_zero_priority(crafted_run):
    _, roles = crafted_run
    assert roles.role[ISOLATED_SEED] == "peripheral"
    assert roles.priority_score[ISOLATED_SEED] == 0


def test_small_dataset_refuses_continuation_estimate(crafted_run):
    stats, _ = crafted_run
    assert stats.model.status == "insufficient_data"
    assert stats.model.auc_cv is None


def test_explicit_collection_produces_no_warnings(crafted_run):
    stats, _ = crafted_run
    assert stats.warnings == []


def test_evidence_is_short_and_numeric(crafted_run):
    _, roles = crafted_run
    assert roles.evidence.str.len().max() <= 200
    assert roles.evidence.str.contains(r"\d").all()


def test_money_cannot_be_traced_backwards_in_time(tmp_path):
    seed, courier, early_recipient = 1, 2, 3
    frames = build_frames([seed], [(courier, early_recipient, 0, 10_000.0), (seed, courier, 5, 10_000.0)])
    run(write_dataset(tmp_path / "input", *frames), tmp_path / "out", tmp_path / "api", JULY)
    features = pd.read_csv(tmp_path / "out" / "features.csv").set_index("gid")
    assert features.traced_in_kzt[early_recipient] == 0
    assert features.traced_in_kzt[courier] == 10_000


def test_traced_money_never_exceeds_inflow(crafted_run, tmp_path):
    features = pd.read_csv(tmp_path / "out" / "features.csv").set_index("gid")
    assert (features.traced_in_kzt <= features.in_kzt + 1).all()


def test_inferred_collection_reports_warnings():
    edges, nodes, tx = crafted_frames()
    collection, warnings = infer_collection(nodes, tx)
    assert collection == Collection(4, "2026-07-02", "2026-07-06", 18_000.0)
    assert len(warnings) == 3


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda e, n, t: (e.drop(columns=["n_tx"]), n, t), "edges.parquet"),
        (lambda e, n, t: (e.assign(sum_kzt=e.sum_kzt + 50), n, t), "transactions"),
        (lambda e, n, t: (e, n.assign(is_seed=False), t), "nodes.is_seed"),
        (lambda e, n, t: (e, n, t.assign(sum_kzt=-t.sum_kzt)), "transactions.sum_kzt"),
        (lambda e, n, t: (e, pd.concat([n, n.head(1)]), t), "nodes.gid"),
    ],
)
def test_invalid_inputs_are_rejected_with_the_offending_field(mutate, field):
    edges, nodes, tx = mutate(*crafted_frames())
    with pytest.raises(DataValidationError) as error:
        validate_inputs(edges, nodes, tx)
    assert field in [issue["field"] for issue in error.value.issues]
