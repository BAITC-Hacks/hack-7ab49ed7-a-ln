from fastapi import APIRouter, Depends

from ..assistant.service import answer
from ..schemas import AssistantAnswer, AssistantRequest
from ..services import Services, get_services, require_auth

router = APIRouter(prefix="/runs/{run_id}", tags=["assistant"], dependencies=[Depends(require_auth)])


@router.post("/assistant", response_model=AssistantAnswer)
def ask(run_id: str, body: AssistantRequest, services: Services = Depends(get_services)) -> dict:
    data = services.run_data(run_id)
    return answer(data, body.question, body.mode, services.llm, services.settings.llm_max_steps).as_dict()
