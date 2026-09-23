from fastapi import APIRouter, Depends, Request, Response

from ..errors import Unauthorized
from ..schemas import SessionLogin, SessionState
from ..security import SESSION_COOKIE, token_matches
from ..services import Services, get_services, is_authenticated

router = APIRouter(prefix="/session", tags=["session"])

COOKIE_PATH = "/api"


@router.get("", response_model=SessionState)
def session_state(request: Request, services: Services = Depends(get_services)) -> SessionState:
    return SessionState(authenticated=is_authenticated(request), auth_required=services.settings.auth_required)


@router.post("", status_code=204, response_class=Response)
def login(body: SessionLogin, request: Request, services: Services = Depends(get_services)) -> Response:
    settings = services.settings
    if not settings.auth_required:
        return Response(status_code=204)
    services.login_limiter.check(request.client.host if request.client else "unknown")
    if not token_matches(settings.api_token, body.token):
        raise Unauthorized("Неверный токен доступа")
    response = Response(status_code=204)
    response.set_cookie(
        SESSION_COOKIE,
        services.signer.issue(),
        max_age=services.signer.ttl_s,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path=COOKIE_PATH,
    )
    return response


@router.delete("", status_code=204, response_class=Response)
def logout(services: Services = Depends(get_services)) -> Response:
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE, path=COOKIE_PATH, httponly=True, samesite="strict", secure=services.settings.cookie_secure
    )
    return response
