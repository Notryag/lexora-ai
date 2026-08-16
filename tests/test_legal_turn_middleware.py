from __future__ import annotations

from unittest.mock import Mock

from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, ToolMessage

from lexora_ai.infrastructure.case_analyst import CASE_ANALYST_TOOL
from lexora_ai.infrastructure.legal_researcher import LEGAL_RESEARCHER_TOOL
from lexora_ai.infrastructure.legal_turn_middleware import (
    LegalDelegationMiddleware,
    _attempted_delegations,
)


def _tool(name: str) -> Mock:
    tool = Mock()
    tool.name = name
    return tool


def _request(messages: list[object]) -> ModelRequest:
    return ModelRequest(
        model=Mock(),
        messages=messages,
        tools=[
            _tool(CASE_ANALYST_TOOL),
            _tool(LEGAL_RESEARCHER_TOOL),
            _tool("calculate_employment_termination_compensation"),
        ],
    )


def _apply(messages: list[object]) -> ModelRequest:
    captured: list[ModelRequest] = []
    LegalDelegationMiddleware().wrap_model_call(
        _request(messages),
        lambda request: captured.append(request) or ModelResponse(result=[]),
    )
    return captured[0]


def test_first_model_call_keeps_dynamic_specialist_choice() -> None:
    request = _request([HumanMessage(content="入户盗窃会判多久？")])
    prepared = _apply(request.messages)

    assert prepared.tool_choice is None
    assert [tool.name for tool in prepared.tools] == [
        CASE_ANALYST_TOOL,
        LEGAL_RESEARCHER_TOOL,
        "calculate_employment_termination_compensation",
    ]


def test_case_analyst_attempt_removes_only_that_specialist() -> None:
    messages = [
        HumanMessage(content="入户盗窃会判多久？"),
        ToolMessage(
            name=CASE_ANALYST_TOOL,
            content='{"subagent":"case_analyst","result":{}}',
            tool_call_id="case-1",
        ),
    ]

    prepared = _apply(messages)

    assert [tool.name for tool in prepared.tools] == [
        LEGAL_RESEARCHER_TOOL,
        "calculate_employment_termination_compensation",
    ]


def test_research_attempt_does_not_force_case_analysis_afterward() -> None:
    messages = [
        HumanMessage(content="民法典如何规定离婚？"),
        ToolMessage(
            name=LEGAL_RESEARCHER_TOOL,
            content='{"subagent":"legal_researcher","result":{}}',
            tool_call_id="research-1",
        ),
    ]

    prepared = _apply(messages)

    assert prepared.tool_choice is None
    assert [tool.name for tool in prepared.tools] == [
        CASE_ANALYST_TOOL,
        "calculate_employment_termination_compensation",
    ]


def test_each_specialist_can_run_at_most_once_even_after_error() -> None:
    messages = [
        HumanMessage(content="分析案件"),
        ToolMessage(
            name=CASE_ANALYST_TOOL,
            content="timeout",
            tool_call_id="case-1",
            status="error",
        ),
        ToolMessage(
            name=LEGAL_RESEARCHER_TOOL,
            content="timeout",
            tool_call_id="research-1",
            status="error",
        ),
    ]

    prepared = _apply(messages)

    assert _attempted_delegations(messages) == {
        CASE_ANALYST_TOOL,
        LEGAL_RESEARCHER_TOOL,
    }
    assert [tool.name for tool in prepared.tools] == [
        "calculate_employment_termination_compensation"
    ]


def test_previous_turn_delegations_do_not_consume_current_turn_budget() -> None:
    messages = [
        HumanMessage(content="上一轮"),
        ToolMessage(
            name=CASE_ANALYST_TOOL,
            content="{}",
            tool_call_id="case-old",
        ),
        HumanMessage(content="这一轮"),
    ]

    assert _attempted_delegations(messages) == set()
