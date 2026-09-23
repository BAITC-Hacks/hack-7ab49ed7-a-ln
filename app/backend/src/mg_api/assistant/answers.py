from dataclasses import dataclass, field

from moneygraph.texts import ROLE_RU

from ..analytics import graphops
from ..analytics.store import RunData

_SUGGESTION_TEMPLATES = (
    "кто собирает деньги с {a}, {b}",
    "откуда деньги у {a}",
    "куда ушли деньги {a}",
    "путь от {b} к {a}",
    "почему {a}",
    "кластер {a}",
    "топ 10 консолидаторов",
)


@dataclass
class Answer:
    intent: str
    answer_markdown: str
    mode_used: str = "offline"
    citations: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    highlight_nodes: list[str] = field(default_factory=list)
    highlight_edges: list[list[str]] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode_used": self.mode_used,
            "intent": self.intent,
            "answer_markdown": self.answer_markdown,
            "citations": self.citations,
            "actions": self.actions,
            "highlight": {"nodes": list(dict.fromkeys(self.highlight_nodes)), "edges": self.highlight_edges},
            "candidates": self.candidates,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }


def suggestions(data: RunData) -> list[str]:
    ids = [t["id"] for t in data.top[:2]] or [str(g) for g in data.nodes.index[:2]]
    a, b = (ids + ids)[:2]
    return [template.format(a=a[-9:], b=b[-9:]) for template in _SUGGESTION_TEMPLATES]


def citation(data: RunData, gid: int, note: str = "") -> dict:
    return {"id": str(gid), "role": data.nodes.role.at[gid], "note": note}


def label(data: RunData, gid: int) -> str:
    row = data.nodes.loc[gid]
    return f"`{gid}` ({ROLE_RU[row.role].lower()}, приоритет {row.priority_score:.2f})"


def resolve_mentions(data: RunData, fragments: list[str]) -> tuple[list[int], list[dict], list[str]]:
    ids, ambiguous, missing = [], [], []
    for fragment in fragments:
        hits = graphops.resolve(data, fragment)
        if len(hits) == 1:
            ids.append(hits[0])
        elif hits:
            ambiguous.append({"fragment": fragment, "ids": [str(h) for h in hits]})
        else:
            missing.append(fragment)
    return list(dict.fromkeys(ids)), ambiguous, missing
