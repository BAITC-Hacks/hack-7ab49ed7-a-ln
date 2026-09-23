"""Экран просмотра: один самодостаточный HTML-файл.

В файл встраиваются шрифт Golos Text (кириллица + латиница), graphology и sigma.js (WebGL-отрисовка
всей сети) и данные graph.json — сеть и CDN не нужны.
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

WEB = Path(__file__).parent / "web"
MARKS = {"fonts": "/*__FONTS__*/", "graphology": "/*__GRAPHOLOGY__*/", "sigma": "/*__SIGMA__*/", "data": "/*__DATA__*/null"}
FONT_WEIGHTS = (400, 500, 600, 700)
# диапазоны unicode-range из fontsource: браузер берёт нужный файл по символам
RANGES = {
    "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
    "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,"
             "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
}


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


def _inline_js(name: str) -> str:
    js = (WEB / "vendor" / name).read_text(encoding="utf-8")
    js = "\n".join(line for line in js.splitlines() if not line.startswith("//# sourceMappingURL"))
    return js.replace("</script", "<\\/script")


def _font_css() -> str:
    rules = []
    for subset, rng in RANGES.items():
        for w in FONT_WEIGHTS:
            data = base64.b64encode((WEB / "fonts" / f"golos-{subset}-{w}.woff2").read_bytes()).decode("ascii")
            rules.append(f'@font-face{{font-family:"Golos Text";font-style:normal;font-weight:{w};font-display:swap;'
                         f'src:url(data:font/woff2;base64,{data}) format("woff2");unicode-range:{rng}}}')
    return "\n".join(rules)


def write_viewer(graph: dict, out_path: Path) -> None:
    """Собирает out/viewer.html из шаблона, шрифтов, библиотек и данных (контракт: docs/graph_json.md)."""
    html = (WEB / "viewer_template.html").read_text(encoding="utf-8")
    parts = {
        "fonts": _font_css(),
        "graphology": _inline_js("graphology.umd.min.js"),
        "sigma": _inline_js("sigma.min.js"),
        "data": _inline_json(graph),
    }
    for key, mark in MARKS.items():
        head, sep, tail = html.partition(mark)
        if not sep:
            raise ValueError(f"в шаблоне нет метки {mark}")
        html = head + parts[key] + tail
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
