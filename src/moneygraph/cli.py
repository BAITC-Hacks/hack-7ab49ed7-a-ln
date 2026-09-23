"""CLI: `moneygraph` (полный прогон), `moneygraph explain <gid|суффикс>`, `moneygraph serve`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _run(args) -> None:
    from moneygraph.pipeline import run

    run(Path(args.data), Path(args.out))


def _explain(args) -> None:
    from moneygraph.cards import explain_text

    print(explain_text(args.query, Path(args.out)))


def _serve(args) -> None:
    from moneygraph.serve import serve

    serve(Path(args.out), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="moneygraph", description="Граф денег: роли, кластеры, приоритеты")
    ap.add_argument("--data", default="data", help="папка с parquet-файлами (по умолчанию data/)")
    ap.add_argument("--out", default="out", help="куда писать выгрузки (по умолчанию out/)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("run", help="полный пересчёт: parquet → выгрузки + экран просмотра (по умолчанию)")
    ex = sub.add_parser("explain", help="карточка узла в терминале")
    ex.add_argument("query", help="полный gid или его последние цифры")
    sv = sub.add_parser("serve", help="экран просмотра + AI-ассистент на http://127.0.0.1:8765")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    {"explain": _explain, "serve": _serve}.get(args.cmd, _run)(args)


if __name__ == "__main__":
    sys.exit(main())
