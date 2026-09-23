"""Экран просмотра: самодостаточный HTML (vis-network и данные встроены в файл, сеть не нужна)."""

from __future__ import annotations

import json
import math
from pathlib import Path

WEB = Path(__file__).parent / "web"
VIS_MARK = "/*__VIS_NETWORK_JS__*/"
DATA_MARK = "/*__GRAPH_DATA__*/null"


def _clean(obj):
    """NaN/inf → null, чтобы данные были валидным JSON."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _inline_json(graph: dict) -> str:
    s = json.dumps(_clean(graph), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # внутри <script> нельзя допустить "</script" и разделители строк JS
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def write_viewer(graph: dict, out_path: Path) -> None:
    """Собирает out/viewer.html из шаблона, vis-network и данных graph.json (контракт: docs/graph_json.md)."""
    template = (WEB / "viewer_template.html").read_text(encoding="utf-8")
    vis_js = (WEB / "vis-network.min.js").read_text(encoding="utf-8")
    vis_js = vis_js.replace("//# sourceMappingURL=vis-network.min.js.map", "").replace("</script", "<\\/script")
    head, rest = template.split(VIS_MARK, 1)
    mid, tail = rest.split(DATA_MARK, 1)
    html = head + vis_js + mid + _inline_json(graph) + tail
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
