import shutil
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from moneygraph.data import REQUIRED_FILES

from ..errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from ..runs.serialize import run_model
from ..runs.uploads import UploadLimits, prepare_input, receive_upload
from ..schemas import Run, RunList
from ..services import Services, get_services, require_auth

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_auth)])

DEMO_NAME = "Демо: HackAlem, июль 2026"
DEMO_PARAMS = {
    "max_depth": 4,
    "observation_start": "2026-07-01",
    "observation_end": "2026-07-31",
    "min_transfer_kzt": 5000.0,
}
_MB = 1024 * 1024


def _upload_limits(services: Services) -> UploadLimits:
    s = services.settings
    return UploadLimits(
        max_upload_bytes=s.max_upload_mb * _MB,
        max_zip_members=s.max_zip_members,
        max_zip_uncompressed_bytes=s.max_zip_uncompressed_mb * _MB,
        max_nodes=s.max_nodes,
        max_transactions=s.max_transactions,
        max_decoded_bytes=s.max_decoded_mb * _MB,
        max_trace_cells=s.max_trace_cells,
    )


def create_demo_run(services: Services) -> dict:
    source = services.settings.demo_data_dir
    if not all((source / f).exists() for f in REQUIRED_FILES):
        raise ServiceUnavailable("Демо-данные не установлены на сервере", retryable=False)
    run_id = str(uuid.uuid4())
    dest = services.run_dir(run_id) / "input"
    dest.mkdir(parents=True)
    for name in REQUIRED_FILES:
        shutil.copyfile(source / name, dest / name)
    return services.runs.create(run_id, DEMO_NAME, "demo", DEMO_PARAMS)


@router.get("", response_model=RunList)
def list_runs(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), services: Services = Depends(get_services)
) -> RunList:
    rows, total = services.runs.page(limit, offset)
    return RunList(items=[run_model(r) for r in rows], total=total)


def _collection_params(
    observation_start: date | None, observation_end: date | None, max_depth: int | None, min_transfer_kzt: float | None
) -> dict:
    if observation_start and observation_end and observation_end < observation_start:
        issue = {"field": "observation_end", "message": "конец окна раньше начала"}
        raise ValidationFailed("Некорректные параметры сбора", details=[issue])
    return {
        "max_depth": max_depth,
        "min_transfer_kzt": min_transfer_kzt,
        "observation_start": observation_start.isoformat() if observation_start else None,
        "observation_end": observation_end.isoformat() if observation_end else None,
    }


@router.post("", response_model=Run, status_code=202)
async def create_run(
    files: list[UploadFile] = File(...),
    name: str | None = Form(None, max_length=200),
    observation_start: date | None = Form(None),
    observation_end: date | None = Form(None),
    max_depth: int | None = Form(None, ge=1, le=50),
    min_transfer_kzt: float | None = Form(None, gt=0, le=1e12, allow_inf_nan=False),
    services: Services = Depends(get_services),
) -> Run:
    params = _collection_params(observation_start, observation_end, max_depth, min_transfer_kzt)
    run_id = str(uuid.uuid4())
    dest = services.run_dir(run_id) / "input"
    limits = _upload_limits(services)
    display_name = name or ", ".join(f.filename or "" for f in files)
    try:
        await receive_upload(files, dest, limits)
        await run_in_threadpool(prepare_input, dest, limits)
        # Inserted last, so the scheduler can never claim a half-uploaded run; `create` commits atomically, so an
        # exception here always means there is no row and the staged input can go.
        row = services.runs.create(run_id, display_name, "upload", params)
    except BaseException:
        shutil.rmtree(services.run_dir(run_id), ignore_errors=True)
        raise
    return run_model(row)


@router.post("/demo", response_model=Run, status_code=202)
def create_demo(services: Services = Depends(get_services)) -> Run:
    return run_model(create_demo_run(services))


@router.get("/{run_id}", response_model=Run)
def get_run(run_id: str, services: Services = Depends(get_services)) -> Run:
    return run_model(services.require_run(run_id))


@router.post("/{run_id}/cancel", response_model=Run, status_code=202)
def cancel_run(run_id: str, services: Services = Depends(get_services)) -> Run:
    outcome = services.runs.cancel(run_id)
    if outcome == "not_found":
        raise NotFound("Прогон не найден")
    if outcome == "final":
        raise Conflict("Прогон уже завершён")
    return run_model(services.require_run(run_id))


@router.post("/{run_id}/retry", response_model=Run, status_code=202)
def retry_run(run_id: str, services: Services = Depends(get_services)) -> Run:
    if not (services.run_dir(run_id) / "input").exists():
        services.require_run(run_id)
        raise Conflict("Входные данные прогона удалены — повтор невозможен")
    outcome = services.runs.retry(run_id)
    if outcome == "not_found":
        raise NotFound("Прогон не найден")
    if outcome == "conflict":
        raise Conflict("Повторить можно только прогон с ошибкой или отменённый")
    return run_model(services.require_run(run_id))


@router.delete("/{run_id}", status_code=204, response_class=Response)
def delete_run(run_id: str, services: Services = Depends(get_services)) -> Response:
    outcome = services.runs.delete(run_id)
    if outcome == "not_found":
        raise NotFound("Прогон не найден")
    if outcome == "conflict":
        raise Conflict("Прогон выполняется — сначала отмените его")
    services.cache.invalidate(run_id)
    shutil.rmtree(services.run_dir(run_id), ignore_errors=True)
    return Response(status_code=204)
