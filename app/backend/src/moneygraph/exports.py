from pathlib import Path

import pandas as pd

from . import config as C

REQUIRED_NODE_COLUMNS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]
REQUIRED_CLUSTER_COLUMNS = ["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]
REQUIRED_TOP_COLUMNS = ["rank", "gid", "role", "priority_score", "why"]
EVIDENCE_MAX_CHARS = 200


class OutputSchemaError(Exception):
    pass


def flags_column(f: pd.DataFrame) -> pd.Series:
    return f["flags"].apply(";".join)


def write_csv_exports(
    out: Path,
    f: pd.DataFrame,
    clusters: pd.DataFrame,
    top: pd.DataFrame,
    resilience_rows: pd.DataFrame,
    requests: pd.DataFrame,
) -> None:
    flags = flags_column(f)
    # Required columns come first and in this order: the case specification checks the schema mechanically.
    pd.DataFrame(
        {
            "gid": f.index,
            "role": f.role.values,
            "role_score": f.role_score.values,
            "cluster_id": f.cluster_id.values,
            "priority_score": f.priority_score.values,
            "evidence": f.evidence.values,
            "flags": flags.values,
            "depth": f.depth.values,
            "is_seed": f.is_seed.values,
            "priority_rank": f["rank"].values,
        }
    ).to_csv(out / "nodes_roles.csv", index=False)
    clusters.to_csv(out / "clusters.csv", index=False)
    top.to_csv(out / "top_nodes.csv", index=False)
    features = f.drop(columns=["evidence"]).assign(flags=flags)
    features.index.name = "gid"
    features.reset_index().to_csv(out / "features.csv", index=False)
    resilience_rows.to_csv(out / "resilience.csv", index=False)
    requests.to_csv(out / "data_requests.csv", index=False)


def _node_problems(roles: pd.DataFrame, nodes: pd.DataFrame) -> list[str]:
    n = len(nodes)
    evidence = roles.evidence.astype(str)
    checks = [
        (list(roles.columns[:6]) == REQUIRED_NODE_COLUMNS, "nodes_roles: порядок обязательных колонок"),
        (len(roles) == n and roles.gid.nunique() == n, "nodes_roles: число строк не равно числу узлов"),
        (set(roles.gid) == set(nodes.gid), "nodes_roles: gid не совпадают с входными узлами"),
        (
            roles[REQUIRED_NODE_COLUMNS].notna().all().all() and (evidence.str.len() > 0).all(),
            "nodes_roles: пустые обязательные поля",
        ),
        (roles.role.isin(C.ROLES).all(), "nodes_roles: роль вне словаря"),
        (
            roles.role_score.between(0, 1).all() and roles.priority_score.between(0, 1).all(),
            "nodes_roles: скор вне [0, 1]",
        ),
        ((evidence.str.len() <= EVIDENCE_MAX_CHARS).all(), "nodes_roles: evidence длиннее 200 символов"),
        (evidence.str.contains(r"\d").all(), "nodes_roles: evidence без чисел"),
    ]
    return [message for ok, message in checks if not ok]


def _cluster_problems(clusters: pd.DataFrame, roles: pd.DataFrame) -> list[str]:
    checks = [
        (list(clusters.columns[:6]) == REQUIRED_CLUSTER_COLUMNS, "clusters: порядок обязательных колонок"),
        (
            set(roles.cluster_id) == set(clusters.cluster_id) and clusters.n_nodes.sum() == len(roles),
            "clusters: не покрывают все узлы",
        ),
        (clusters.hypothesis.notna().all(), "clusters: пустая гипотеза"),
    ]
    return [message for ok, message in checks if not ok]


def _top_problems(top: pd.DataFrame, n_nodes: int) -> list[str]:
    checks = [
        (list(top.columns[:5]) == REQUIRED_TOP_COLUMNS, "top_nodes: порядок обязательных колонок"),
        (len(top) == min(C.TOP_N, n_nodes), "top_nodes: неверная длина"),
        (
            top["rank"].is_monotonic_increasing and top.priority_score.is_monotonic_decreasing,
            "top_nodes: нарушен порядок",
        ),
    ]
    return [message for ok, message in checks if not ok]


def validate_outputs(out: Path, nodes: pd.DataFrame) -> None:
    roles = pd.read_csv(out / "nodes_roles.csv")
    problems = (
        _node_problems(roles, nodes)
        + _cluster_problems(pd.read_csv(out / "clusters.csv"), roles)
        + _top_problems(pd.read_csv(out / "top_nodes.csv"), len(nodes))
    )
    first_gid = (out / "nodes_roles.csv").read_text().splitlines()[1].split(",")[0]
    if not first_gid.lstrip("-").isdigit():
        problems.append("nodes_roles: gid записан не целым числом")
    if problems:
        raise OutputSchemaError("; ".join(problems))
