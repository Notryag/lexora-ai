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


class LegalTurnPreparationMiddleware(AgentMiddleware):
    """Require one structured Lexora preparation step before each final answer."""

    @staticmethod
    def _prepare_request(request: ModelRequest) -> ModelRequest:
        if _turn_is_prepared(request.messages):
            return request
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
