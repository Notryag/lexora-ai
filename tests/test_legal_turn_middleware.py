from __future__ import annotations

from unittest.mock import Mock

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

from lexora_ai.infrastructure.legal_turn_middleware import (
    PREPARE_LEGAL_TURN_TOOL,
    LegalTurnPreparationMiddleware,
    _turn_is_prepared,
)


def _request(messages: list[object]) -> ModelRequest:
    preparation = Mock(name="preparation_tool")
    preparation.name = PREPARE_LEGAL_TURN_TOOL
    search = Mock(name="search_tool")
    search.name = "search_legal_authorities"
    return ModelRequest(model=Mock(), messages=messages, tools=[preparation, search])


def test_first_model_call_is_forced_to_prepare_turn() -> None:
    middleware = LegalTurnPreparationMiddleware()
    captured: list[ModelRequest] = []

    middleware.wrap_model_call(
        _request([HumanMessage(content="入户盗窃会判多久？")]),
        lambda request: captured.append(request) or ModelResponse(result=[]),
    )

    assert captured[0].tool_choice == {
        "type": "function",
        "name": PREPARE_LEGAL_TURN_TOOL,
    }
    assert [tool.name for tool in captured[0].tools] == [PREPARE_LEGAL_TURN_TOOL]


def test_successful_preparation_unlocks_final_model_call() -> None:
    middleware = LegalTurnPreparationMiddleware()
    messages = [
        HumanMessage(content="入户盗窃会判多久？"),
        ToolMessage(
            name=PREPARE_LEGAL_TURN_TOOL,
            content='{"review_required":false}',
            tool_call_id="prepare-1",
        ),
    ]
    request = _request(messages)
    captured: list[ModelRequest] = []

    middleware.wrap_model_call(
        request,
        lambda prepared: captured.append(prepared) or ModelResponse(result=[]),
    )

    assert _turn_is_prepared(messages)
    assert captured[0] is not request
    assert captured[0].tool_choice is None
    assert [tool.name for tool in captured[0].tools] == ["search_legal_authorities"]


def test_old_or_failed_preparation_does_not_unlock_current_turn() -> None:
    messages = [
        HumanMessage(content="上一轮"),
        ToolMessage(
            name=PREPARE_LEGAL_TURN_TOOL,
            content="{}",
            tool_call_id="prepare-old",
        ),
        HumanMessage(content="这一轮"),
        ToolMessage(
            name=PREPARE_LEGAL_TURN_TOOL,
            content="validation error",
            tool_call_id="prepare-failed",
            status="error",
        ),
    ]

    assert not _turn_is_prepared(messages)
