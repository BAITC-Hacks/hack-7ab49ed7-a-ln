from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analytics.store import RunCache
from .assistant.llm import AnthropicLLM, LLMClient
from .errors import ApiError
from .logging_setup import setup_logging
from .middleware import RequestContextMiddleware, UploadGuardMiddleware, error_body
from .routers import analytics, assistant, exports, meta, runs, session
from .routers.runs import create_demo_run
from .runs.repository import SqliteRunRepository
from .runs.scheduler import ProcessLauncher, Scheduler, WorkerLauncher
from .schemas import ErrorResponse
from .security import LoginRateLimiter, SessionSigner
from .services import Services, is_authenticated
from .settings import VERSION, Settings

API_PREFIX = "/api/v1"
ERROR_RESPONSES = {
    status: {"model": ErrorResponse, "description": description}
    for status, description in (
        (400, "Некорректные входные данные"),
        (401, "Требуется вход"),
        (404, "Не найдено"),
        (409, "Конфликт состояния прогона"),
        (413, "Слишком большая загрузка"),
        (422, "Некорректные параметры запроса"),
        (429, "Слишком много запросов"),
        (500, "Внутренняя ошибка"),
        (503, "Сервис временно недоступен"),
    )
}

_VALIDATION_MESSAGES = {
    "missing": lambda ctx: "обязательное поле",
    "string_too_short": lambda ctx: f"не короче {ctx.get('min_length')} символов",
    "string_too_long": lambda ctx: f"не длиннее {ctx.get('max_length')} символов",
    "string_pattern_mismatch": lambda ctx: "неверный формат",
    "greater_than_equal": lambda ctx: f"значение должно быть ≥ {ctx.get('ge')}",
    "greater_than": lambda ctx: f"значение должно быть > {ctx.get('gt')}",
    "less_than_equal": lambda ctx: f"значение должно быть ≤ {ctx.get('le')}",
    "int_parsing": lambda ctx: "ожидается целое число",
    "float_parsing": lambda ctx: "ожидается число",
    "finite_number": lambda ctx: "ожидается конечное число",
    "bool_parsing": lambda ctx: "ожидается true или false",
    "date_from_datetime_parsing": lambda ctx: "ожидается дата ГГГГ-ММ-ДД",
    "literal_error": lambda ctx: f"допустимые значения: {ctx.get('expected')}",
    "too_long": lambda ctx: f"не больше {ctx.get('max_length')} элементов",
}


_HTTP_ERRORS = {
    400: ("validation_error", "Некорректное тело запроса"),
    404: ("not_found", "Ресурс не найден"),
    405: ("method_not_allowed", "Метод не поддерживается"),
}


def _localized(error: dict) -> str:
    render = _VALIDATION_MESSAGES.get(error.get("type"))
    return render(error.get("ctx") or {}) if render else error["msg"]


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details, exc.retryable), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": _localized(e)} for e in exc.errors()
        ]
        return JSONResponse(error_body("validation_error", "Некорректные параметры запроса", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_ERRORS.get(exc.status_code, ("http_error", f"Ошибка HTTP {exc.status_code}"))
        return JSONResponse(error_body(code, message), status_code=exc.status_code)


def _install_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        UploadGuardMiddleware,
        path=f"{API_PREFIX}/runs",
        limit_bytes=settings.max_upload_mb * 1024 * 1024,
        authorize=is_authenticated,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)


def _default_llm(settings: Settings) -> LLMClient | None:
    if not settings.llm_available:
        return None
    return AnthropicLLM(settings.anthropic_api_key, settings.llm_model, settings.llm_timeout_s)


def create_app(
    settings: Settings | None = None, launcher: WorkerLauncher | None = None, llm: LLMClient | None = None
) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.log_level, settings.log_json)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    repository = SqliteRunRepository(settings.db_path)
    scheduler = Scheduler(settings, repository, launcher or ProcessLauncher()) if settings.scheduler_enabled else None
    services = Services(
        settings=settings,
        runs=repository,
        cache=RunCache(settings.cache_mb),
        signer=SessionSigner(settings.signing_key, settings.session_ttl_hours * 3600),
        login_limiter=LoginRateLimiter(settings.login_attempts_per_minute),
        llm=llm or _default_llm(settings),
        scheduler=scheduler,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.seed_demo and repository.count() == 0 and settings.demo_data_dir.exists():
            create_demo_run(services)
        if scheduler:
            scheduler.start()
        yield
        if scheduler:
            scheduler.stop()

    # The schema is served by an authenticated route in routers/meta.py; Swagger UI is not shipped because it
    # loads CDN assets the deployed CSP forbids.
    app = FastAPI(
        title="MoneyGraph API", version=VERSION, lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None
    )
    app.state.services = services
    _install_error_handlers(app)
    _install_middleware(app, settings)
    for module in (meta, session, runs, analytics, assistant, exports):
        app.include_router(module.router, prefix=API_PREFIX, responses=ERROR_RESPONSES)
    return app
