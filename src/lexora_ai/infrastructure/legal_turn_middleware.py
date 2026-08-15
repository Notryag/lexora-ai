from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ModelCallResult,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage, ToolMessage

from lexora_ai.infrastructure.case_analyst import CASE_ANALYST_TOOL

PREPARE_LEGAL_TURN_TOOL = "prepare_legal_turn"


def _turn_is_prepared(messages: list[object]) -> bool:
    latest_human = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        -1,
    )
    return any(
        isinstance(message, ToolMessage)
        and message.name == PREPARE_LEGAL_TURN_TOOL
        and getattr(message, "status", "success") != "error"
        for message in messages[latest_human + 1 :]
    )


def _turn_assessment_intent(messages: list[object]) -> str | None:
    latest_human = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        -1,
    )
    for message in reversed(messages[latest_human + 1 :]):
        if not isinstance(message, ToolMessage) or message.name != CASE_ANALYST_TOOL:
            continue
        if getattr(message, "status", "success") == "error" or not isinstance(
            message.content, str
        ):
            return None
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            return None
        result = payload.get("result") if isinstance(payload, dict) else None
        intent = result.get("intent") if isinstance(result, dict) else None
        return intent if isinstance(intent, str) else None
    return None


class LegalTurnPreparationMiddleware(AgentMiddleware):
    """Require case assessment and non-social preparation before a final answer."""

    @staticmethod
    def _prepare_request(request: ModelRequest) -> ModelRequest:
        assessment_intent = _turn_assessment_intent(request.messages)
        if _turn_is_prepared(request.messages) or assessment_intent == "social":
            return request.override(
                tools=[
                    tool
                    for tool in request.tools
                    if getattr(tool, "name", None)
                    not in {PREPARE_LEGAL_TURN_TOOL, CASE_ANALYST_TOOL}
                ]
            )
        if assessment_intent is None:
            assessment_tools = [
                tool
                for tool in request.tools
                if getattr(tool, "name", None) == CASE_ANALYST_TOOL
            ]
            preparation_tools = [
                tool
                for tool in request.tools
                if getattr(tool, "name", None) == PREPARE_LEGAL_TURN_TOOL
            ]
            if len(assessment_tools) != 1:
                raise RuntimeError("case analyst tool is required exactly once")
            if len(preparation_tools) != 1:
                raise RuntimeError("prepare_legal_turn tool is required exactly once")
            return request.override(
                tools=[*assessment_tools, *preparation_tools],
                tool_choice="required",
            )
        preparation_tools = [
            tool for tool in request.tools if getattr(tool, "name", None) == PREPARE_LEGAL_TURN_TOOL
        ]
        if len(preparation_tools) != 1:
            raise RuntimeError("prepare_legal_turn tool is required exactly once")
        return request.override(
            tools=preparation_tools,
            tool_choice={
                "type": "function",
                "name": PREPARE_LEGAL_TURN_TOOL,
            },
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._prepare_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        return await handler(self._prepare_request(request))
