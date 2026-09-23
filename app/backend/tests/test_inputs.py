import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from moneygraph.data import (
    DataValidationError,
    InspectionLimits,
    inspect_inputs,
    parse_dates,
    read_inputs,
    validate_inputs,
)
from moneygraph.pipeline import CollectionOverrides, run

from .datasets import crafted_frames, write_dataset


def _fields(error: pytest.ExceptionInfo) -> list[str]:
    return [issue["field"] for issue in error.value.issues]


@pytest.fixture
def dataset(tmp_path):
    return write_dataset(tmp_path / "input", *crafted_frames())


def test_well_formed_input_passes_inspection(dataset):
    inspect_inputs(dataset, InspectionLimits(max_nodes=100, max_transactions=100, max_trace_cells=1000))


@pytest.mark.parametrize(
    "limits, field",
    [
        (InspectionLimits(max_nodes=5), "nodes.parquet"),
        (InspectionLimits(max_transactions=5), "transactions.parquet"),
        (InspectionLimits(max_decoded_bytes=100), "data"),
        (InspectionLimits(max_trace_cells=10), "nodes.is_seed"),
    ],
)
def test_inspection_enforces_size_limits_from_the_footer(dataset, limits, field):
    with pytest.raises(DataValidationError) as error:
        inspect_inputs(dataset, limits)
    assert field in _fields(error)


def test_inspection_rejects_wrong_column_types(tmp_path):
    edges, nodes, tx = crafted_frames()
    dataset = write_dataset(tmp_path / "input", edges, nodes.assign(gid=nodes.gid.astype(str)), tx.assign(date=1))
    with pytest.raises(DataValidationError) as error:
        inspect_inputs(dataset, InspectionLimits())
    assert _fields(error) == ["nodes.gid", "transactions.date"]


LONG_DATE = "2026-07-01" + " " * 5000


def test_repeated_long_dates_are_rejected_before_expansion(tmp_path):
    edges, nodes, tx = crafted_frames()
    dataset = write_dataset(tmp_path / "input", edges, nodes, tx.assign(date=LONG_DATE))
    inspect_inputs(dataset, InspectionLimits(max_decoded_bytes=2**20))
    with pytest.raises(DataValidationError) as error:
        read_inputs(dataset)
    assert _fields(error) == ["transactions.date"]


def test_plain_encoded_text_counts_at_its_stored_size(tmp_path):
    edges, nodes, tx = crafted_frames()
    dataset = write_dataset(tmp_path / "input", edges, nodes, tx)
    tx.assign(date=LONG_DATE).to_parquet(dataset / "transactions.parquet", index=False, use_dictionary=False)
    with pytest.raises(DataValidationError) as error:
        inspect_inputs(dataset, InspectionLimits(max_decoded_bytes=100_000))
    assert _fields(error) == ["data"]


def test_repeated_required_columns_are_rejected(dataset):
    nodes = pq.read_table(dataset / "nodes.parquet")
    doubled = pa.Table.from_arrays([nodes["gid"], *nodes.columns], names=["gid", *nodes.column_names])
    pq.write_table(doubled, dataset / "nodes.parquet")
    with pytest.raises(DataValidationError) as error:
        inspect_inputs(dataset, InspectionLimits())
    assert _fields(error) == ["nodes.parquet"]


def _corrupt_column(path, column: str) -> None:
    metadata = pq.ParquetFile(path).metadata
    chunk = metadata.row_group(0).column(metadata.schema.names.index(column))
    start = chunk.dictionary_page_offset or chunk.data_page_offset
    data = bytearray(path.read_bytes())
    data[start : start + chunk.total_compressed_size] = b"\xff" * chunk.total_compressed_size
    path.write_bytes(bytes(data))


def test_unreadable_seed_flags_are_a_validation_error(dataset):
    _corrupt_column(dataset / "nodes.parquet", "is_seed")
    with pytest.raises(DataValidationError) as error:
        inspect_inputs(dataset, InspectionLimits(max_trace_cells=10**9))
    assert _fields(error) == ["nodes.is_seed"]


def test_missing_files_are_reported_by_name(dataset):
    (dataset / "edges.parquet").unlink()
    with pytest.raises(DataValidationError) as error:
        inspect_inputs(dataset, InspectionLimits())
    assert _fields(error) == ["edges.parquet"]


def test_ids_beyond_int64_are_rejected():
    edges, nodes, tx = crafted_frames()
    nodes = nodes.assign(gid=nodes.gid.astype("uint64"))
    nodes.loc[0, "gid"] = 2**64 - 1
    with pytest.raises(DataValidationError) as error:
        validate_inputs(edges, nodes, tx)
    assert _fields(error) == ["nodes.gid"]


def test_numeric_dates_are_rejected():
    edges, nodes, tx = crafted_frames()
    with pytest.raises(DataValidationError) as error:
        validate_inputs(edges, nodes, tx.assign(date=range(len(tx))))
    assert _fields(error) == ["transactions.date"]


def test_dates_with_offsets_are_brought_to_utc():
    parsed = parse_dates(pd.Series(["2026-07-02T03:00:00+05:00", "2026-07-02T03:00:00+06:00", "2026-07-02"]))
    assert list(parsed.astype(str)) == ["2026-07-01 22:00:00", "2026-07-01 21:00:00", "2026-07-02 00:00:00"]


def test_time_zone_aware_dates_run_end_to_end(tmp_path):
    edges, nodes, tx = crafted_frames()
    aware = tx.assign(date=pd.to_datetime(tx.date).dt.tz_localize("UTC"))
    july = CollectionOverrides(observation_start="2026-07-01", observation_end="2026-07-31")
    stats = run(write_dataset(tmp_path / "input", edges, nodes, aware), tmp_path / "out", tmp_path / "api", july)
    assert stats.collection.start == pd.Timestamp("2026-07-01") and (tmp_path / "out" / "nodes_roles.csv").exists()
