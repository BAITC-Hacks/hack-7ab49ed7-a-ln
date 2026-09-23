import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from moneygraph import config as engine_config
from moneygraph.data import DataValidationError
from moneygraph.exports import OutputSchemaError
from moneygraph.pipeline import CollectionOverrides, InputLimits
from moneygraph.pipeline import run as run_engine

from .repository import RunFailure, RunOutcome, SqliteRunRepository

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobSpec:
    run_id: str
    claim: str
    attempt: int
    db_path: str
    runs_dir: str
    overrides: CollectionOverrides
    limits: InputLimits
    log_level: str
    log_json: bool

    @classmethod
    def from_dict(cls, data: dict) -> "JobSpec":
        nested = {"overrides": CollectionOverrides(**data["overrides"]), "limits": InputLimits(**data["limits"])}
        return cls(**{**data, **nested})


def _swap_current(base: Path, work: Path) -> None:
    # os.replace on a symlink is atomic, so readers never see a half-written result.
    tmp_link = base / f".current-{uuid.uuid4().hex}"
    os.symlink(work.relative_to(base), tmp_link)
    os.replace(tmp_link, base / "current")


def _remove_stale_attempts(base: Path, published: Path) -> None:
    for attempt in (base / "attempts").iterdir():
        if attempt != published:
            shutil.rmtree(attempt, ignore_errors=True)


def execute_run(job: JobSpec) -> None:
    from ..logging_setup import setup_logging

    setup_logging(job.log_level, job.log_json)
    runs = SqliteRunRepository(Path(job.db_path))
    base = Path(job.runs_dir) / job.run_id
    # Unique per attempt: a retry must never write into the directory `current` points at.
    work = base / "attempts" / f"{job.attempt}-{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True)

    def report_progress(code: str, label: str, fraction: float) -> None:
        runs.progress(job.run_id, job.claim, code, label, fraction)

    try:
        stats = run_engine(base / "input", work / "out", work / "api", job.overrides, job.limits, report_progress)
    except DataValidationError as e:
        failure = RunFailure("validation_error", "Данные не прошли проверку", False, details=e.issues)
        runs.finish_failed(job.run_id, job.claim, failure)
        return
    except OutputSchemaError as e:
        log.error("run %s produced invalid outputs: %s", job.run_id, e)
        failure = RunFailure("engine_error", f"Ошибка формирования выгрузок: {e}", False)
        runs.finish_failed(job.run_id, job.claim, failure)
        return
    except Exception as e:
        # Process boundary: any engine failure is recorded on the run so the user can see and retry it.
        log.exception("run %s failed", job.run_id)
        failure = RunFailure("engine_error", f"Ошибка расчёта: {type(e).__name__}: {e}", True)
        runs.finish_failed(job.run_id, job.claim, failure)
        return
    summary = json.loads((work / "api" / "meta.json").read_text())["summary"]
    outcome = RunOutcome(summary, stats.collection.as_dict(), stats.warnings, engine_config.ENGINE_VERSION)
    if runs.publish_and_succeed(job.run_id, job.claim, outcome, lambda: _swap_current(base, work)):
        _remove_stale_attempts(base, work)
    else:
        log.warning("run %s: claim lost or cancelled before publication; result discarded", job.run_id)
        shutil.rmtree(work, ignore_errors=True)
