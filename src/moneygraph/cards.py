"""Карточка узла: текстовая справка по клиенту из out/graph.json (CLI `explain` и AI-ассистент)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from moneygraph.config import confidence_level, priority_level

_CACHE: dict[str, tuple[float, dict]] = {}


def load_graph(out_dir: Path) -> dict:
    """Читает out/graph.json; кэш сбрасывается, если файл перезаписан."""
    path = Path(out_dir) / "graph.json"
    mtime = path.stat().st_mtime
    key = str(path.resolve())
    cached = _CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    graph = json.loads(path.read_text(encoding="utf-8"))
    _CACHE[key] = (mtime, graph)
    return graph


def index(graph: dict) -> dict:
    """Индексы по графу (строятся один раз и хранятся в graph["_idx"])."""
    idx = graph.get("_idx")
    if idx is not None:
        return idx
    by_id = {n["id"]: n for n in graph["nodes"]}
    ins: dict[str, list[dict]] = {g: [] for g in by_id}
    outs: dict[str, list[dict]] = {g: [] for g in by_id}
    for e in graph["edges"]:
        outs.setdefault(e["from"], []).append(e)
        ins.setdefault(e["to"], []).append(e)
    for lst in (*ins.values(), *outs.values()):
        lst.sort(key=lambda e: -e["sum"])
    idx = {
        "by_id": by_id,
        "in": ins,
        "out": outs,
        "clusters": {c["id"]: c for c in graph.get("clusters", [])},
        "top": {t["gid"]: t for t in graph.get("top", [])},
        "by_rank": sorted(by_id.values(), key=lambda n: (n.get("rank") or 10**9)),
    }
    graph["_idx"] = idx
    return idx


def resolve(query: str, graph: dict) -> list[str]:
    """Полный gid → [gid]; иначе совпадения по окончанию, затем по подстроке (по убыванию приоритета)."""
    q = re.sub(r"\D", "", str(query))
    if not q:
        return []
    idx = index(graph)
    if q in idx["by_id"]:
        return [q]
    ranked = idx["by_rank"]
    hits = [n["id"] for n in ranked if n["id"].endswith(q)]
    if not hits:
        hits = [n["id"] for n in ranked if q in n["id"]]
    return hits


# ---------------------------------------------------------------- форматирование

def fmt_kzt(x: float | None) -> str:
    """1 820 000 → «1,82 млн ₸»; 254 000 → «254 тыс ₸»; 5 000 → «5 000 ₸»."""
    if x is None:
        return "—"
    x = float(x)
    if abs(x) >= 1e6:
        return f"{x / 1e6:.2f}".replace(".", ",") + " млн ₸"
    if abs(x) >= 1e4:
        return f"{x / 1e3:.0f} тыс ₸"
    return f"{x:,.0f}".replace(",", " ") + " ₸"


def role_ru(graph: dict, role: str) -> str:
    return graph.get("meta", {}).get("roles", {}).get(role, {}).get("ru", role)


def short_gid(gid: str) -> str:
    return f"…{gid[-6:]}"


def _dates(e: dict, limit: int = 3) -> str:
    days = sorted({d for d, _ in e.get("tx", [])})
    s = ", ".join(d[5:] for d in days[:limit])  # «07-03»
    return s + (", …" if len(days) > limit else "")


def _counterparty_line(arrow: str, other: str, e: dict, graph: dict) -> str:
    n = index(graph)["by_id"].get(other, {})
    seed = ", seed" if n.get("is_seed") else ""
    return (f"  {arrow} {other} [{role_ru(graph, n.get('role', '?'))}{seed}] {fmt_kzt(e['sum'])}, "
            f"{e['n_tx']} перев. ({_dates(e)})")


def node_card(gid: str, graph: dict, max_counterparties: int = 5) -> str:
    """Человекочитаемая карточка узла (русский текст)."""
    idx = index(graph)
    n = idx["by_id"].get(gid)
    if n is None:
        return f"Узел {gid} не найден в графе."
    meta = graph.get("meta", {})
    total = meta.get("n_nodes", len(idx["by_id"]))
    lines = []
    tags = [f"колено {n.get('depth')}"]
    if n.get("is_seed"):
        tags.insert(0, "seed")
    lines.append(f"gid {gid}  [{', '.join(tags)}]")

    role_line = (f"Роль: {role_ru(graph, n['role'])} — роль выражена {confidence_level(n.get('role_score', 0))} "
                 f"({round(100 * (n.get('role_score') or 0))}%)")
    if n.get("alt_role"):
        role_line += f" · также признаки: {role_ru(graph, n['alt_role'])}"
    lines.append(role_line)
    if n.get("typology"):
        lines.append(f"Типология AML: {n['typology']}")
    if n.get("rule_fired"):
        lines.append(f"Правило: {n['rule_fired']}")
    if n.get("evidence"):
        lines.append(f"Обоснование: {n['evidence']}")

    parts = n.get("prio_parts") or {}
    part_names = {"role": "роль", "flow": "оборот", "centrality": "центральность", "seed": "связь с seed",
                  "flags": "флаги"}
    parts_s = " + ".join(f"{part_names.get(k, k)} {v:.2f}" for k, v in parts.items())
    rank = n.get("rank") or 0
    lines.append(f"Приоритет проверки: {priority_level(rank)}, №{rank} из {total} "
                 f"(балл {n.get('priority', 0):.2f}" + (f" = {parts_s})" if parts_s else ")"))

    c = idx["clusters"].get(n.get("cluster"))
    if c is not None:
        stab = f", устойчивость {c['stability']:.2f}" if c.get("stability") is not None else ""
        lines.append(f"Кластер {c['id']} ({c['n_nodes']} узл., {c['n_seed']} seed{stab}): {c.get('hypothesis', '')}")
    else:
        lines.append(f"Кластер {n.get('cluster')}")

    status = {"confirmed_sink": "исходящих нет (выгружены полностью) — деньги остаются",
              "truncated_depth": "4-е колено: исходящие не выгружены (обрыв обхода)",
              "truncated_time": "поступления в конце июля: пересылка могла уйти в август",
              "not_sink": "есть исходящие переводы",
              "no_data": "нет переводов ≥5 000 ₸ в выгрузке"}.get(n.get("sink_status"), n.get("sink_status"))
    st = f"Статус стока: {status}"
    if n.get("truncated") and n.get("p_forward") is not None:
        st += f"; оценка P(пересылает дальше) = {n['p_forward']:.0%}"
    lines.append(st)

    flag_names = meta.get("flags", {})
    if n.get("flags"):
        lines.append("Флаги: " + "; ".join(flag_names.get(f, f) for f in n["flags"]))

    m = (f"Метрики: входящие — {n.get('in_deg', 0)} плательщ., {n.get('in_tx', 0)} перев., "
         f"{fmt_kzt(n.get('in_kzt'))}; исходящие — {n.get('out_deg', 0)} получат., {n.get('out_tx', 0)} перев., "
         f"{fmt_kzt(n.get('out_kzt'))}")
    if n.get("fast_share") is not None:
        m += f"; переслано за ≤2 дн: {n['fast_share']:.0%} входящих"
    m += f"; PageRank {n.get('pagerank', 0):.4f}; посредничество {n.get('betweenness', 0):.4f}"
    lines.append(m)

    ins, outs = idx["in"].get(gid, []), idx["out"].get(gid, [])
    if ins:
        lines.append(f"Крупнейшие плательщики ({min(len(ins), max_counterparties)} из {len(ins)}):")
        lines += [_counterparty_line("←", e["from"], e, graph) for e in ins[:max_counterparties]]
    if outs:
        lines.append(f"Крупнейшие получатели ({min(len(outs), max_counterparties)} из {len(outs)}):")
        lines += [_counterparty_line("→", e["to"], e, graph) for e in outs[:max_counterparties]]
    if not ins and not outs:
        lines.append("Связей в выгрузке нет.")
    return "\n".join(lines)


def match_line(gid: str, graph: dict) -> str:
    n = index(graph)["by_id"][gid]
    seed = ", seed" if n.get("is_seed") else ""
    rank = n.get("rank") or 0
    return (f"  {gid}  {role_ru(graph, n['role'])}{seed}, приоритет {priority_level(rank)} "
            f"(№{rank}), кластер {n.get('cluster')}")


def explain_text(query: str, out_dir: Path) -> str:
    """Карточка для одного совпадения, список — для нескольких, сообщение — если ничего не найдено."""
    try:
        graph = load_graph(out_dir)
    except FileNotFoundError:
        return f"Нет {Path(out_dir) / 'graph.json'} — сначала запустите `uv run moneygraph`."
    hits = resolve(query, graph)
    if not hits:
        return f"Узел по запросу «{query}» не найден (искали полный gid, окончание и подстроку)."
    if len(hits) == 1:
        return node_card(hits[0], graph)
    shown = hits[:20]
    head = f"Найдено {len(hits)} узлов по «{query}» — уточните (показаны {len(shown)} по приоритету):"
    return "\n".join([head, *(match_line(g, graph) for g in shown)])
