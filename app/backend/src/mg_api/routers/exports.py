import os
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..errors import NotFound
from ..schemas import ExportItem, ExportList
from ..services import Services, get_services, require_auth

router = APIRouter(prefix="/runs/{run_id}/exports", tags=["exports"], dependencies=[Depends(require_auth)])


@dataclass(frozen=True)
class ExportFile:
    name: str
    filename: str
    content_type: str
    description: str


EXPORTS = (
    ExportFile("nodes_roles", "nodes_roles.csv", "text/csv", "Роль, скоры, кластер и обоснование каждого узла"),
    ExportFile("clusters", "clusters.csv", "text/csv", "Кластеры с гипотезами назначения"),
    ExportFile("top_nodes", "top_nodes.csv", "text/csv", "Топ-лист приоритетов с обоснованием"),
    ExportFile("features", "features.csv", "text/csv", "Все признаки узлов, правила и компоненты приоритета"),
    ExportFile("resilience", "resilience.csv", "text/csv", "Устойчивость сети при блокировке топ-N узлов"),
    ExportFile("data_requests", "data_requests.csv", "text/csv", "Какие данные запросить следующими"),
    ExportFile("run_report", "run_report.md", "text/markdown", "Отчёт прогона"),
)
BUNDLE = ExportFile("bundle", "moneygraph-results.zip", "application/zip", "Все выгрузки одним архивом")


def _out_dir(services: Services, run_id: str) -> Path:
    services.run_data(run_id)
    return (services.run_dir(run_id) / "current").resolve() / "out"


def _bundle(out: Path) -> Path:
    target = out / BUNDLE.filename
    if not target.exists():
        # Built once per published attempt; concurrent builders race harmlessly on the atomic rename.
        tmp = out / f".{uuid.uuid4().hex}.zip"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for export in EXPORTS:
                z.write(out / export.filename, export.filename)
        os.replace(tmp, target)
    return target


@router.get("", response_model=ExportList)
def list_exports(run_id: str, services: Services = Depends(get_services)) -> ExportList:
    out = _out_dir(services, run_id)
    items = [
        ExportItem(
            name=e.name,
            filename=e.filename,
            content_type=e.content_type,
            size_bytes=(out / e.filename).stat().st_size,
            description=e.description,
        )
        for e in EXPORTS
    ]
    items.append(
        ExportItem(
            name=BUNDLE.name,
            filename=BUNDLE.filename,
            content_type=BUNDLE.content_type,
            size_bytes=None,
            description=BUNDLE.description,
        )
    )
    return ExportList(items=items)


@router.get("/{name}", response_class=FileResponse)
def download(run_id: str, name: str, services: Services = Depends(get_services)) -> FileResponse:
    out = _out_dir(services, run_id)
    if name == BUNDLE.name:
        return FileResponse(_bundle(out), media_type=BUNDLE.content_type, filename=BUNDLE.filename)
    export = next((e for e in EXPORTS if e.name == name), None)
    if export is None:
        raise NotFound("Нет такой выгрузки")
    return FileResponse(out / export.filename, media_type=export.content_type, filename=export.filename)
