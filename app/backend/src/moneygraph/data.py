from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .collection import Collection

REQUIRED_FILES = ("edges.parquet", "nodes.parquet", "transactions.parquet")
SCHEMA = {
    "edges": ["src", "dst", "sum_kzt", "n_tx", "depth"],
    "nodes": ["gid", "depth", "is_seed"],
    "transactions": ["src", "dst", "date", "sum_kzt"],
}
ID_COLUMNS = {"edges": ["src", "dst"], "nodes": ["gid"], "transactions": ["src", "dst"]}
INT64_MAX = 2**63 - 1
MAX_DATE_TEXT = 40
# In-memory cost per value once loaded into pandas: dates and text become Python objects, numbers 8-byte arrays.
_OBJECT_BYTES = 64
_NUMERIC_BYTES = 8

Issue = dict


def _issue(field: str, message: str) -> Issue:
    return {"field": field, "message": message}


@dataclass
class DataValidationError(Exception):
    issues: list = field(default_factory=list)

    def __str__(self) -> str:
        return "; ".join(f"{i['field']}: {i['message']}" for i in self.issues[:10])


@dataclass(frozen=True)
class InspectionLimits:
    max_nodes: int | None = None
    max_transactions: int | None = None
    max_decoded_bytes: int | None = None
    max_trace_cells: int | None = None


def _require_files(data_dir: Path) -> None:
    missing = [f for f in REQUIRED_FILES if not (data_dir / f).exists()]
    if missing:
        raise DataValidationError([_issue(f, "файл отсутствует") for f in missing])


def _is_text(arrow_type: pa.DataType) -> bool:
    return pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type)


def _loaded_width(arrow_type: pa.DataType) -> int:
    if _is_text(arrow_type):
        return _OBJECT_BYTES + MAX_DATE_TEXT
    if pa.types.is_date(arrow_type) or pa.types.is_timestamp(arrow_type):
        return _OBJECT_BYTES
    return _NUMERIC_BYTES


def _stored_bytes(metadata: pq.FileMetaData) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for g in range(metadata.num_row_groups):
        group = metadata.row_group(g)
        for c in range(group.num_columns):
            column = group.column(c)
            sizes[column.path_in_schema] = sizes.get(column.path_in_schema, 0) + column.total_uncompressed_size
    return sizes


def _type_problem(name: str, column: str, arrow_type: pa.DataType) -> str | None:
    if column in ID_COLUMNS[name] or column in ("n_tx", "depth"):
        return None if pa.types.is_integer(arrow_type) else "ожидаются целые числа"
    if column == "sum_kzt":
        return None if pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type) else "ожидаются числа"
    if column == "is_seed":
        return None if pa.types.is_boolean(arrow_type) or pa.types.is_integer(arrow_type) else "ожидается true/false"
    dated = pa.types.is_date(arrow_type) or pa.types.is_timestamp(arrow_type)
    return None if _is_text(arrow_type) or dated else "ожидаются даты или строки ГГГГ-ММ-ДД"


def _inspect_file(data_dir: Path, name: str, row_limit: int | None) -> tuple[list[Issue], int, int]:
    path = data_dir / f"{name}.parquet"
    try:
        metadata = pq.ParquetFile(path).metadata
        schema = pq.read_schema(path)
    except (OSError, pa.ArrowException) as e:
        return [_issue(f"{name}.parquet", f"не читается как parquet: {e}")], 0, 0
    rows = sum(metadata.row_group(g).num_rows for g in range(metadata.num_row_groups))
    missing = [c for c in SCHEMA[name] if c not in schema.names]
    if missing:
        return [_issue(f"{name}.parquet", f"нет колонок: {', '.join(missing)}")], 0, rows
    repeated = [c for c in SCHEMA[name] if schema.names.count(c) > 1]
    if repeated:
        return [_issue(f"{name}.parquet", f"колонки повторяются: {', '.join(repeated)}")], 0, rows
    issues = [
        _issue(f"{name}.{c}", problem)
        for c in SCHEMA[name]
        if (problem := _type_problem(name, c, schema.field(c).type))
    ]
    if row_limit and rows > row_limit:
        issues.append(_issue(f"{name}.parquet", f"слишком много строк: {rows} > {row_limit}"))
    # Encoded sizes understate memory (dictionary/RLE pages expand), so the estimate is per value, and never
    # below what the pages themselves hold.
    stored = _stored_bytes(metadata)
    loaded = sum(max(rows * _loaded_width(schema.field(c).type), stored.get(c, 0)) for c in SCHEMA[name])
    return issues, loaded, rows


def _count_seeds(path: Path) -> int:
    try:
        return int(pq.read_table(path, columns=["is_seed"]).column("is_seed").to_pandas().astype(bool).sum())
    except (OSError, ValueError, pa.ArrowException) as e:
        raise DataValidationError([_issue("nodes.is_seed", f"не читается: {e}")]) from e


def inspect_inputs(data_dir: Path, limits: InspectionLimits) -> None:
    # Reads only parquet footers (plus the seed flags) so that oversized or hostile files are rejected before
    # anything is decompressed into memory.
    _require_files(data_dir)
    row_limits = {"nodes": limits.max_nodes, "edges": limits.max_transactions, "transactions": limits.max_transactions}
    issues, loaded, rows = [], 0, {}
    for name in SCHEMA:
        file_issues, file_bytes, rows[name] = _inspect_file(data_dir, name, row_limits[name])
        issues += file_issues
        loaded += file_bytes
    if limits.max_decoded_bytes and loaded > limits.max_decoded_bytes:
        issues.append(
            _issue(
                "data",
                f"данные займут в памяти около {loaded // 2**20} МБ при лимите {limits.max_decoded_bytes // 2**20} МБ",
            )
        )
    if issues:
        raise DataValidationError(issues)
    if limits.max_trace_cells:
        seeds = _count_seeds(data_dir / "nodes.parquet")
        if rows["nodes"] * seeds > limits.max_trace_cells:
            raise DataValidationError(
                [_issue("nodes.is_seed", f"слишком много seed для трассировки: {seeds} seed × {rows['nodes']} узлов")]
            )


def _longest_text(column: pa.ChunkedArray) -> int:
    return max((pc.max(pc.utf8_length(chunk.dictionary)).as_py() or 0 for chunk in column.chunks), default=0)


def _read_table(name: str, path: Path) -> pd.DataFrame:
    text = [f.name for f in pq.read_schema(path) if f.name in SCHEMA[name] and _is_text(f.type)]
    # Text stays dictionary-encoded until its length is checked: a small file can repeat one huge value per row.
    table = pq.read_table(path, columns=SCHEMA[name], read_dictionary=text)
    for column in text:
        if _longest_text(table[column]) > MAX_DATE_TEXT:
            raise DataValidationError([_issue(f"{name}.{column}", f"значения длиннее {MAX_DATE_TEXT} символов")])
        table = table.set_column(table.schema.get_field_index(column), column, table[column].cast(pa.string()))
    return table.to_pandas()


def read_inputs(data_dir: Path):
    _require_files(data_dir)
    frames = {}
    for name in SCHEMA:
        try:
            frames[name] = _read_table(name, data_dir / f"{name}.parquet")
        except (OSError, ValueError, pa.ArrowException) as e:
            raise DataValidationError([_issue(f"{name}.parquet", f"не читается как parquet: {e}")]) from e
    return frames["edges"], frames["nodes"], frames["transactions"]


def parse_dates(values: pd.Series) -> pd.Series:
    # Values with an offset or time zone are brought to UTC (mixed offsets included); naive values keep their
    # wall-clock time, which is how the reference data stores plain dates.
    kind = pd.api.types.infer_dtype(values, skipna=True)
    if kind in ("integer", "floating", "mixed-integer-float", "decimal", "boolean"):
        return pd.Series(pd.NaT, index=values.index)
    parsed = pd.to_datetime(values, errors="coerce", utc=True, format="ISO8601" if kind == "string" else None)
    return parsed.dt.tz_localize(None)


def _missing_columns(edges, nodes, tx) -> list[Issue]:
    return [
        _issue(f"{name}.parquet", f"нет колонок: {', '.join(miss)}")
        for name, df in (("edges", edges), ("nodes", nodes), ("transactions", tx))
        if (miss := [c for c in SCHEMA[name] if c not in df.columns])
    ]


def _bad_ids(name: str, df: pd.DataFrame) -> list[Issue]:
    issues = []
    for c in ID_COLUMNS[name]:
        ids = df[c]
        if ids.isna().any() or not pd.api.types.is_integer_dtype(ids):
            issues.append(_issue(f"{name}.{c}", "ожидаются целые идентификаторы без пропусков"))
        elif len(ids) and (ids.min() < 0 or int(ids.max()) > INT64_MAX):
            issues.append(_issue(f"{name}.{c}", "идентификаторы должны быть в диапазоне 0 … 2^63−1"))
    return issues


def _bad_types(edges, nodes, tx) -> list[Issue]:
    issues = _bad_ids("edges", edges) + _bad_ids("nodes", nodes) + _bad_ids("transactions", tx)
    for name, df, cols in (("edges", edges, ["n_tx", "depth"]), ("nodes", nodes, ["depth"])):
        issues += [
            _issue(f"{name}.{c}", "ожидаются целые числа без пропусков")
            for c in cols
            if df[c].isna().any() or not pd.api.types.is_integer_dtype(df[c])
        ]
    for name, df in (("edges", edges), ("transactions", tx)):
        amounts = df["sum_kzt"]
        numeric = pd.api.types.is_numeric_dtype(amounts) and not pd.api.types.is_bool_dtype(amounts)
        if not numeric or amounts.isna().any() or not np.isfinite(amounts).all() or (amounts <= 0).any():
            issues.append(_issue(f"{name}.sum_kzt", "суммы должны быть положительными числами"))
    seed = nodes["is_seed"]
    if seed.isna().any() or not (pd.api.types.is_bool_dtype(seed) or set(pd.unique(seed)) <= {0, 1}):
        issues.append(_issue("nodes.is_seed", "ожидается логическое значение (true/false)"))
    bad_dates = parse_dates(tx["date"]).isna().sum()
    if bad_dates:
        issues.append(
            _issue(
                "transactions.date",
                f"не распознаны даты в {int(bad_dates)} строках (ожидаются даты или строки ГГГГ-ММ-ДД)",
            )
        )
    return issues


def _bad_values(edges, nodes, tx, max_nodes, max_transactions) -> list[Issue]:
    checks = [
        (
            len(nodes) == 0 or len(edges) == 0 or len(tx) == 0,
            "data",
            "таблицы узлов, рёбер и транзакций не должны быть пустыми",
        ),
        (
            bool(max_nodes) and len(nodes) > max_nodes,
            "nodes.parquet",
            f"слишком много узлов: {len(nodes)} > {max_nodes}",
        ),
        (
            bool(max_transactions) and len(tx) > max_transactions,
            "transactions.parquet",
            f"слишком много транзакций: {len(tx)} > {max_transactions}",
        ),
        (not nodes["gid"].is_unique, "nodes.gid", "идентификаторы узлов повторяются"),
        (not nodes["is_seed"].astype(bool).any(), "nodes.is_seed", "нет ни одного seed-клиента"),
        (
            (nodes["depth"] < 0).any() or (edges["depth"] < 1).any(),
            "depth",
            "колено должно быть ≥ 0 у узлов и ≥ 1 у рёбер",
        ),
        ((edges["n_tx"] < 1).any(), "edges.n_tx", "число операций на ребре должно быть ≥ 1"),
        (edges.duplicated(["src", "dst"]).any(), "edges", "пары (src, dst) повторяются — ожидается агрегат по паре"),
        ((edges["src"] == edges["dst"]).any(), "edges", "переводы самому себе не поддерживаются"),
    ]
    issues = [_issue(f, m) for failed, f, m in checks if failed]
    unknown = (set(edges["src"]) | set(edges["dst"])) - set(nodes["gid"])
    if unknown:
        issues.append(_issue("edges", f"{len(unknown)} gid из рёбер нет в nodes.parquet"))
    return issues


def _inconsistent_aggregates(edges, tx) -> list[Issue]:
    agg = tx.groupby(["src", "dst"]).agg(s=("sum_kzt", "sum"), c=("sum_kzt", "size")).reset_index()
    m = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    unmatched = int((m["_merge"] != "both").sum())
    if unmatched:
        return [_issue("transactions", f"{unmatched} пар не совпадают между рёбрами и транзакциями")]
    if not (((m.s - m.sum_kzt).abs() <= 1).all() and (m.c == m.n_tx).all()):
        return [_issue("transactions", "суммы или число операций по парам не совпадают с edges.parquet")]
    return []


def validate_inputs(
    edges: pd.DataFrame,
    nodes: pd.DataFrame,
    tx: pd.DataFrame,
    max_nodes: int | None = None,
    max_transactions: int | None = None,
) -> None:
    stages = (
        lambda: _missing_columns(edges, nodes, tx),
        lambda: _bad_types(edges, nodes, tx),
        lambda: _bad_values(edges, nodes, tx, max_nodes, max_transactions),
        lambda: _inconsistent_aggregates(edges, tx),
    )
    for stage in stages:
        issues = stage()
        if issues:
            raise DataValidationError(issues)


def normalize(edges, nodes, tx, collection: Collection):
    edges = edges[SCHEMA["edges"]].copy()
    nodes = nodes[SCHEMA["nodes"]].copy()
    tx = tx[SCHEMA["transactions"]].copy()
    for df, cols in ((edges, ["src", "dst"]), (nodes, ["gid"]), (tx, ["src", "dst"])):
        for c in cols:
            df[c] = df[c].astype("int64")
    nodes["is_seed"] = nodes["is_seed"].astype(bool)
    nodes["depth"] = nodes["depth"].astype(int)
    edges["depth"] = edges["depth"].astype(int)
    edges["n_tx"] = edges["n_tx"].astype(int)
    edges["sum_kzt"] = edges["sum_kzt"].astype(float)
    tx["sum_kzt"] = tx["sum_kzt"].astype(float)
    tx["date"] = parse_dates(tx["date"]).dt.normalize()
    tx["day"] = (tx["date"] - collection.start).dt.days
    nodes = nodes.sort_values("gid").reset_index(drop=True)
    edges = edges.sort_values(["src", "dst"]).reset_index(drop=True)
    tx = tx.sort_values(["date", "src", "dst", "sum_kzt"]).reset_index(drop=True)
    return edges, nodes, tx


def infer_collection(
    nodes: pd.DataFrame,
    tx: pd.DataFrame,
    max_depth=None,
    observation_start=None,
    observation_end=None,
    min_transfer_kzt=None,
) -> tuple[Collection, list[str]]:
    warnings = []
    dates = parse_dates(tx["date"])
    observed_depth, observed_min = int(nodes["depth"].max()), float(tx["sum_kzt"].min())
    if max_depth is None:
        max_depth = int(nodes["depth"].max())
        warnings.append(f"глубина обхода не задана — взята по данным: {max_depth}")
    if observation_start is None or observation_end is None:
        observation_start = observation_start or str(dates.min().date())
        observation_end = observation_end or str(dates.max().date())
        warnings.append(
            f"окно наблюдения не задано — взято по датам транзакций: {observation_start} — {observation_end}"
        )
    if min_transfer_kzt is None:
        min_transfer_kzt = float(tx["sum_kzt"].min())
        warnings.append(
            f"порог суммы выгрузки не задан — взят минимум по данным: {min_transfer_kzt:,.0f} ₸".replace(",", " ")
        )
    issues = []
    if max_depth < max(1, observed_depth):
        issues.append(
            _issue("max_depth", f"в данных есть узлы на колене {observed_depth} — глубина обхода не может быть меньше")
        )
    if not np.isfinite(min_transfer_kzt) or min_transfer_kzt <= 0:
        issues.append(_issue("min_transfer_kzt", "порог суммы должен быть положительным числом"))
    elif min_transfer_kzt > observed_min:
        issues.append(
            _issue("min_transfer_kzt", f"в данных есть переводы меньше порога: {observed_min:,.0f} ₸".replace(",", " "))
        )
    if issues:
        raise DataValidationError(issues)
    if pd.Timestamp(observation_end) < pd.Timestamp(observation_start):
        raise DataValidationError([_issue("observation_end", "конец окна раньше начала")])
    if dates.min() < pd.Timestamp(observation_start) or dates.max() > pd.Timestamp(observation_end):
        warnings.append("часть транзакций лежит вне заданного окна наблюдения")
    return Collection(int(max_depth), str(observation_start), str(observation_end), float(min_transfer_kzt)), warnings


def sanity_check(edges, nodes, tx) -> dict:
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "transactions": len(tx),
        "seeds": int(nodes.is_seed.sum()),
        "total_kzt": float(edges.sum_kzt.sum()),
        "isolated": len(set(nodes.gid) - (set(edges.src) | set(edges.dst))),
        "period": [str(tx.date.min().date()), str(tx.date.max().date())],
    }


def build_graph(edges, nodes) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(int(g) for g in nodes.gid)
    for e in edges.itertuples(index=False):
        G.add_edge(
            int(e.src),
            int(e.dst),
            sum_kzt=float(e.sum_kzt),
            n_tx=int(e.n_tx),
            depth=int(e.depth),
            distance=1.0 / float(e.sum_kzt),
        )
    return G
