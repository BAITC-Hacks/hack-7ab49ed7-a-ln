"""Загрузка parquet, проверки консистентности, сборка направленного взвешенного графа."""
import zipfile
from pathlib import Path

import networkx as nx
import pandas as pd

from . import config as C


REQUIRED = ("edges.parquet", "nodes.parquet", "transactions.parquet")


def ensure_data(data_dir: Path) -> None:
    """Если data/ ещё не распакована, берём parquet из архива организаторов (data*.zip) рядом с проектом."""
    if all((data_dir / f).exists() for f in REQUIRED):
        return
    for zpath in sorted({*Path.cwd().glob("data*.zip"), *data_dir.parent.glob("data*.zip")}):
        with zipfile.ZipFile(zpath) as z:
            members = {Path(m).name: m for m in z.namelist()
                       if Path(m).name in REQUIRED and not m.startswith("__MACOSX")}
            if set(members) == set(REQUIRED):
                data_dir.mkdir(parents=True, exist_ok=True)
                for name, m in members.items():
                    (data_dir / name).write_bytes(z.read(m))
                print(f"Распаковал {', '.join(REQUIRED)} из «{zpath.name}» в {data_dir}/", flush=True)
                return
    missing = [f for f in REQUIRED if not (data_dir / f).exists()]
    raise SystemExit(f"Не найдены входные файлы: {', '.join(str(data_dir / f) for f in missing)}.\n"
                     f"Положите parquet-файлы в {data_dir}/ (или архив data*.zip рядом с run.py) "
                     f"либо укажите путь: uv run run.py --data путь/к/data")


def load(data_dir: Path):
    ensure_data(data_dir)
    edges = pd.read_parquet(data_dir / "edges.parquet")
    nodes = pd.read_parquet(data_dir / "nodes.parquet")
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    for df, cols in ((edges, ["src", "dst"]), (nodes, ["gid"]), (tx, ["src", "dst"])):
        for c in cols:
            df[c] = df[c].astype("int64")
    tx["date"] = pd.to_datetime(tx["date"])
    tx["day"] = (tx["date"] - pd.Timestamp(C.OBSERVATION_START)).dt.days
    nodes = nodes.sort_values("gid").reset_index(drop=True)
    edges = edges.sort_values(["src", "dst"]).reset_index(drop=True)
    tx = tx.sort_values(["date", "src", "dst", "sum_kzt"]).reset_index(drop=True)
    return edges, nodes, tx


def sanity_check(edges, nodes, tx) -> dict:
    agg = tx.groupby(["src", "dst"]).agg(s=("sum_kzt", "sum"), c=("sum_kzt", "size")).reset_index()
    m = edges.merge(agg, on=["src", "dst"], how="outer", indicator=True)
    assert (m["_merge"] == "both").all(), "edges и transactions не сходятся по парам"
    assert ((m.s - m.sum_kzt).abs() < 1).all() and (m.c == m.n_tx).all(), "суммы/число операций не сходятся"
    assert nodes.gid.is_unique
    in_graph = set(edges.src) | set(edges.dst)
    assert in_graph <= set(nodes.gid), "в рёбрах есть gid, которых нет в nodes"
    return {"nodes": len(nodes), "edges": len(edges), "transactions": len(tx),
            "seeds": int(nodes.is_seed.sum()), "total_kzt": float(edges.sum_kzt.sum()),
            "isolated": len(set(nodes.gid) - in_graph),
            "period": [str(tx.date.min().date()), str(tx.date.max().date())]}


def build_graph(edges, nodes) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(int(g) for g in nodes.gid)
    for e in edges.itertuples(index=False):
        G.add_edge(int(e.src), int(e.dst), sum_kzt=float(e.sum_kzt), n_tx=int(e.n_tx),
                   depth=int(e.depth), distance=1.0 / float(e.sum_kzt))
    return G
