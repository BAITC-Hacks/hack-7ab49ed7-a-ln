import pytest

from mg_api.assistant.agent import answer_with_llm
from mg_api.assistant.llm import LLMUnavailable
from mg_api.assistant.offline import answer_offline
from mg_api.assistant.service import answer
from mg_api.errors import ServiceUnavailable

from .fakes import FakeLLM, response, text_block, tool_block


@pytest.fixture(scope="module")
def data(demo_client):
    return demo_client.app.state.services.run_data(demo_client.run_id)


@pytest.fixture(scope="module")
def top(data):
    return [t["id"] for t in data.top[:3]]


def test_collectors_intent_finds_common_downstream_nodes(data, top):
    result = answer_offline(data, f"кто собирает деньги с {top[0]}, {top[1]}")
    assert result.intent == "collectors" and result.highlight_nodes
    assert any("Достижимость" in w for w in result.warnings)


def test_explain_intent_accepts_a_unique_fragment(data, top):
    result = answer_offline(data, f"почему {top[0][-9:]}")
    assert result.intent == "explain" and result.citations[0]["id"] == top[0]


def test_ambiguous_fragment_returns_candidates(data):
    result = answer_offline(data, "почему 100000")
    assert result.intent == "ambiguous" and len(result.candidates[0]["ids"]) > 1


@pytest.mark.parametrize(
    "question, intent",
    [
        ("топ 5 консолидаторов", "top"),
        ("кластер 1", "cluster"),
        ("привет", "help"),
    ],
)
def test_template_intents(data, question, intent):
    assert answer_offline(data, question).intent == intent


def test_path_intent_marks_undirected_fallback(data, top):
    result = answer_offline(data, f"путь от {top[0]} к {top[1]}")
    assert result.intent == "path"


def test_llm_agent_runs_tools_and_cites_nodes(data, top):
    llm = FakeLLM(
        [
            response("tool_use", tool_block("t1", "get_node", {"gid": top[0]})),
            response("end_turn", text_block(f"Узел {top[0]} — признаки консолидации.")),
        ]
    )
    result = answer_with_llm(data, "что с первым узлом?", llm, max_steps=4)
    assert result.mode_used == "llm" and result.citations[0]["id"] == top[0]
    tool_results = llm.requests[1]["messages"][-1]["content"]
    assert tool_results[0]["tool_use_id"] == "t1" and "is_error" not in tool_results[0]


@pytest.mark.parametrize(
    "name, tool_input",
    [
        ("get_node", {"gid": "1"}),
        ("get_node", {"gid": 123456789}),
        ("top_nodes", {"limit": "many"}),
        ("top_nodes", {"role": "boss"}),
        ("cluster_info", {"cluster_id": -1}),
        ("trace", {"gid": "123456", "direction": "up", "max_hops": 99}),
        ("common_collectors", {"gids": []}),
        ("search_nodes", {"fragment": "123", "extra": True}),
        ("drop_tables", {}),
    ],
)
def test_bad_tool_input_is_returned_to_the_model_as_an_error(data, name, tool_input):
    llm = FakeLLM(
        [
            response("tool_use", tool_block("t1", name, tool_input)),
            response("end_turn", text_block("Не получилось.")),
        ]
    )
    answer_with_llm(data, "?", llm, max_steps=4)
    result = llm.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and result["content"].startswith("Ошибка")


def test_refusal_is_reported_as_a_warning(data):
    result = answer_with_llm(data, "?", FakeLLM([response("refusal")]), max_steps=2)
    assert result.warnings and result.answer_markdown == "Модель не дала ответа."


class _UnavailableLLM:
    def create(self, **_):
        raise LLMUnavailable("Нет соединения с API модели")


def test_auto_mode_falls_back_to_offline(data):
    result = answer(data, "топ 3", "auto", _UnavailableLLM(), max_steps=2)
    assert result.mode_used == "offline" and result.warnings[0].startswith("Нет соединения")


def test_llm_mode_surfaces_unavailability(data):
    with pytest.raises(ServiceUnavailable):
        answer(data, "топ 3", "llm", _UnavailableLLM(), max_steps=2)


def test_llm_mode_without_a_configured_model_is_rejected(data):
    with pytest.raises(ServiceUnavailable):
        answer(data, "топ 3", "llm", None, max_steps=2)
