import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastapi import UploadFile

from moneygraph.data import REQUIRED_FILES, DataValidationError, InspectionLimits, inspect_inputs

from ..errors import PayloadTooLarge, ValidationFailed

_CHUNK = 1024 * 1024
_ARCHIVE = "upload.zip"
_KEYWORDS = {"edges": "edges.parquet", "nodes": "nodes.parquet", "transactions": "transactions.parquet"}


@dataclass(frozen=True)
class UploadLimits:
    max_upload_bytes: int
    max_zip_members: int
    max_zip_uncompressed_bytes: int
    max_nodes: int
    max_transactions: int
    max_decoded_bytes: int
    max_trace_cells: int


def _target_name(filename: str) -> str | None:
    stem = PurePosixPath(filename).name.lower()
    if not stem.endswith(".parquet"):
        return None
    return next((target for key, target in _KEYWORDS.items() if stem.startswith(key)), None)


class _ByteBudget:
    def __init__(self, limit: int):
        self._remaining = limit

    def spend(self, n: int) -> None:
        self._remaining -= n
        if self._remaining < 0:
            raise PayloadTooLarge("Загрузка превышает допустимый размер")


async def _stream_to(upload: UploadFile, dest: Path, budget: _ByteBudget) -> None:
    with dest.open("wb") as out:
        while chunk := await upload.read(_CHUNK):
            budget.spend(len(chunk))
            out.write(chunk)


def _extract_zip(archive: Path, dest: Path, limits: UploadLimits) -> None:
    try:
        with zipfile.ZipFile(archive) as z:
            members = [m for m in z.infolist() if not m.is_dir()]
            if len(members) > limits.max_zip_members:
                raise ValidationFailed(f"В архиве слишком много файлов: {len(members)} > {limits.max_zip_members}")
            if sum(m.file_size for m in members) > limits.max_zip_uncompressed_bytes:
                raise PayloadTooLarge("Распакованный архив превышает допустимый размер")
            picked = {}
            for member in members:
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts or path.parts[0] == "__MACOSX":
                    continue
                target = _target_name(path.name)
                if target:
                    if target in picked:
                        raise ValidationFailed(f"В архиве несколько файлов для {target}")
                    picked[target] = member
            missing = [f for f in REQUIRED_FILES if f not in picked]
            if missing:
                raise ValidationFailed(
                    "В архиве не найдены файлы", details=[{"field": f, "message": "файл отсутствует"} for f in missing]
                )
            for target, member in picked.items():
                # Members are copied by name into a fixed destination: archive paths are never used on disk.
                with z.open(member) as src, (dest / target).open("wb") as out:
                    shutil.copyfileobj(src, out, _CHUNK)
    except zipfile.BadZipFile as e:
        raise ValidationFailed("Файл не является корректным zip-архивом") from e
    except NotImplementedError as e:
        raise ValidationFailed("Архив сжат неподдерживаемым методом — используйте обычный ZIP (deflate)") from e


async def receive_upload(files: list[UploadFile], dest: Path, limits: UploadLimits) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    budget = _ByteBudget(limits.max_upload_bytes)
    names = [f.filename or "" for f in files]
    if len(files) == 1 and names[0].lower().endswith(".zip"):
        await _stream_to(files[0], dest / _ARCHIVE, budget)
        return
    if len(files) != 3:
        raise ValidationFailed("Загрузите один zip-архив или ровно три parquet-файла")
    targets = [_target_name(n) for n in names]
    if sorted(t for t in targets if t) != sorted(REQUIRED_FILES):
        raise ValidationFailed(
            "Нужны три файла: edges.parquet, nodes.parquet, transactions.parquet",
            details=[{"field": "files", "message": f"получено: {', '.join(names)}"}],
        )
    for upload, target in zip(files, targets, strict=True):
        await _stream_to(upload, dest / target, budget)


def prepare_input(dest: Path, limits: UploadLimits) -> None:
    archive = dest / _ARCHIVE
    if archive.exists():
        _extract_zip(archive, dest, limits)
        archive.unlink()
    inspection = InspectionLimits(
        limits.max_nodes, limits.max_transactions, limits.max_decoded_bytes, limits.max_trace_cells
    )
    try:
        inspect_inputs(dest, inspection)
    except DataValidationError as e:
        raise ValidationFailed("Данные не прошли проверку", details=e.issues) from e
