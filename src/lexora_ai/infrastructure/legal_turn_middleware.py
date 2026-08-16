from __future__ import annotations

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
from lexora_ai.infrastructure.legal_researcher import LEGAL_RESEARCHER_TOOL

_DELEGATION_TOOLS = {CASE_ANALYST_TOOL, LEGAL_RESEARCHER_TOOL}


def _current_turn_messages(messages: list[object]) -> list[object]:
    latest_human = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        -1,
    )
    return messages[latest_human + 1 :]


def _attempted_delegations(messages: list[object]) -> set[str]:
    return {
        message.name
        for message in _current_turn_messages(messages)
        if isinstance(message, ToolMessage) and message.name in _DELEGATION_TOOLS
    }


class LegalDelegationMiddleware(AgentMiddleware):
    """Keep specialist routing dynamic while bounding repeat delegation."""

    @staticmethod
    def _prepare_request(request: ModelRequest) -> ModelRequest:
        attempted = _attempted_delegations(request.messages)
        if not attempted:
            return request
        return request.override(
            tools=[
                tool
                for tool in request.tools
                if getattr(tool, "name", None) not in attempted
            ]
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
