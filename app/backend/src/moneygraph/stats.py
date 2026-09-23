from dataclasses import asdict, dataclass

from .collection import Collection
from .features import ContinuationModel


@dataclass
class RunStats:
    summary: dict
    collection: Collection
    warnings: list[str]
    engine_version: str
    roles: dict[str, int]
    n_clusters: int
    model: ContinuationModel
    cycles: dict[str, int]
    flags: dict[str, int]
    resilience_base: dict
    resilience_rows: list[dict]
    data_requests: dict[str, int]
    runtime_s: float | None = None

    def as_dict(self) -> dict:
        data = asdict(self)
        data["collection"] = self.collection.as_dict()
        return data
