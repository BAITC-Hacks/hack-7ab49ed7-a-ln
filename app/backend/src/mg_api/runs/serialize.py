import json
from datetime import datetime, timezone

from ..schemas import Run, RunError, RunParams, RunSummary

_POLL_MS = {"queued": 1500, "running": 1000}


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_model(row: dict) -> Run:
    error = (
        RunError(
            code=row["error_code"],
            message=row["error_message"],
            retryable=bool(row["error_retryable"]),
            details=json.loads(row["error_details"]) if row["error_details"] else None,
        )
        if row["error_code"]
        else None
    )
    summary = json.loads(row["summary"]) if row["summary"] else None
    return Run(
        id=row["id"],
        name=row["name"],
        source=row["source"],
        status=row["status"],
        cancel_requested=bool(row["cancel_requested"]),
        stage_code=row["stage_code"],
        stage_label=row["stage_label"],
        progress=row["progress"],
        error=error,
        attempts=row["attempts"],
        created_at=_iso(row["created_at"]),
        updated_at=_iso(row["updated_at"]),
        started_at=_iso(row["started_at"]),
        finished_at=_iso(row["finished_at"]),
        duration_s=round(row["duration_s"], 1) if row["duration_s"] is not None else None,
        poll_after_ms=_POLL_MS.get(row["status"]),
        params=RunParams(**json.loads(row["params"])),
        warnings=json.loads(row["warnings"]),
        summary=RunSummary(**summary) if summary else None,
        engine_version=row["engine_version"],
    )
