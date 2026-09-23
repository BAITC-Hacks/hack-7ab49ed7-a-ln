import tempfile

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from moneygraph import config as engine_config
from moneygraph.collection import Collection
from moneygraph.priority import COMPONENT_RU
from moneygraph.report import role_rules_text
from moneygraph.texts import FLAG_RU, ROLE_COLORS, ROLE_RU

from ..errors import ServiceUnavailable
from ..schemas import Health, Limits, Meta, Methodology
from ..services import Services, get_services, require_auth
from ..settings import VERSION

router = APIRouter(tags=["meta"])

LIMITATIONS = [
    "Роли — гипотезы для проверки по структуре и суммам переводов, а не утверждение о виновности.",
    "Видны только внутрибанковские переводы выше порога суммы выгрузки: наличные, межбанк и дробление ниже "
    "порога не видны.",
    "Узлы последнего колена обхода не раскрывались: их исходящие неизвестны.",
    "Входящие seed-клиентов из-за пределов выгрузки не видны, поэтому отношение «отдал/получил» для них не считается.",
    "Даты без времени: порядок операций внутри дня условен; маршруты и трассировка — совместимость по датам, "
    "а не доказанное движение одних и тех же денег.",
    "Оценка продолжения цепочки для узлов обрыва — модель по аналогии с раскрытыми коленами, не вероятность.",
]


@router.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=VERSION)


@router.get("/ready", response_model=Health)
def ready(services: Services = Depends(get_services)) -> Health:
    services.runs.ping()
    with tempfile.NamedTemporaryFile(dir=services.settings.data_dir):
        pass
    if services.scheduler is not None and not services.scheduler.healthy:
        raise ServiceUnavailable("Планировщик прогонов остановлен")
    return Health(status="ready", version=VERSION)


@router.get("/meta", response_model=Meta)
def meta(services: Services = Depends(get_services)) -> Meta:
    s = services.settings
    return Meta(
        version=VERSION,
        auth_required=s.auth_required,
        llm_enabled=services.llm is not None,
        limits=Limits(
            max_upload_mb=s.max_upload_mb,
            max_zip_members=s.max_zip_members,
            max_nodes=s.max_nodes,
            max_transactions=s.max_transactions,
        ),
    )


@router.get("/methodology", response_model=Methodology, dependencies=[Depends(require_auth)])
def methodology(run_id: str | None = Query(None), services: Services = Depends(get_services)) -> Methodology:
    collection = None
    if run_id is not None:
        params = services.run_data(run_id).meta["params"]
        collection = Collection(
            params["max_depth"], params["observation_start"], params["observation_end"], params["min_transfer_kzt"]
        )
    rules = role_rules_text(collection)
    return Methodology(
        roles={r: {"label": ROLE_RU[r], "color": ROLE_COLORS[r], "rule": rules[r]} for r in engine_config.ROLES},
        role_order=list(engine_config.ROLES),
        flags=FLAG_RU,
        priority_components=[
            {"key": k, "label": COMPONENT_RU[k], "weight": w} for k, w in engine_config.PRIORITY_WEIGHTS.items()
        ],
        limitations=LIMITATIONS,
    )


@router.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_auth)])
def openapi_schema(request: Request) -> JSONResponse:
    return JSONResponse(request.app.openapi())
