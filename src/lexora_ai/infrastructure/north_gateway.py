from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage
from north import (
    AppClient,
    AppConfig,
    MemoryStreamBridge,
    RunExecutor,
    RuntimeStreamEvent,
    build_agent,
)
from north.runtime import RunManager

from lexora_ai.application import (
    ConversationCaseLawChunk,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    ConversationRetrievalPort,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
)
from lexora_ai.config import Settings
from lexora_ai.domain import CaseAnalysisRequest, ConversationTurnRequest
from lexora_ai.infrastructure.north_tools import build_legal_retrieval_tools
from lexora_ai.prompts import (
    LEXORA_SYSTEM_PROMPT,
    build_case_analysis_prompt,
    build_conversation_prompt,
)


class ModelNotConfiguredError(RuntimeError):
    pass


class NorthCaseAnalysisGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AppClient | None = None

    async def analyze(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID,
    ) -> GeneratedCaseAnalysis:
        client = self._get_client()
        response = await asyncio.to_thread(
            client.chat,
            build_case_analysis_prompt(request),
            thread_id=str(analysis_id),
        )
        return GeneratedCaseAnalysis(
            content=str(response),
            runtime_thread_id=response.thread_id,
        )

    async def converse(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval: ConversationRetrievalPort | None = None,
    ) -> GeneratedConversationTurn:
        return await self._run_conversation(
            request,
            thread_id=thread_id,
            on_text_delta=lambda _delta: None,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval=retrieval,
        )

    async def converse_stream(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        on_text_delta: Callable[[str], None],
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval: ConversationRetrievalPort | None = None,
    ) -> GeneratedConversationTurn:
        return await self._run_conversation(
            request,
            thread_id=thread_id,
            on_text_delta=on_text_delta,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval=retrieval,
        )

    async def _run_conversation(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        on_text_delta: Callable[[str], None],
        history: tuple[ConversationContextMessage, ...],
        evidence: tuple[ConversationEvidenceChunk, ...] | None,
        legal_authorities: tuple[ConversationLegalChunk, ...],
        case_law_authorities: tuple[ConversationCaseLawChunk, ...],
        retrieval: ConversationRetrievalPort | None,
    ) -> GeneratedConversationTurn:
        prompt = build_conversation_prompt(
            request,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval_available=retrieval is not None,
        )
        run_id = str(thread_id)
        manager = RunManager()
        record = manager.create(thread_id=run_id, run_id=run_id)

        async def observe(event: RuntimeStreamEvent) -> None:
            if event.mode != "messages" or event.namespace:
                return
            delta = _assistant_text_delta(event.data)
            if delta:
                on_text_delta(delta)

        result = await RunExecutor(MemoryStreamBridge(), manager).execute(
            record,
            agent_factory=lambda: build_agent(
                self._get_config(),
                tools=build_legal_retrieval_tools(retrieval),
            ),
            graph_input={"messages": [HumanMessage(content=prompt)]},
            config={
                "configurable": {"thread_id": run_id},
                "recursion_limit": self._get_config().recursion_limit,
            },
            context={"thread_id": run_id, "run_id": run_id},
            stream_observer=observe,
            publish_modes=(),
        )
        content = _final_assistant_text(result.values)
        if not content:
            raise RuntimeError("North did not return an assistant message")
        return GeneratedConversationTurn(content=content, runtime_thread_id=run_id)

    def _get_config(self) -> AppConfig:
        client = self._get_client()
        return client.config

    def _get_client(self) -> AppClient:
        if self._client is not None:
            return self._client
        if self._settings.openai_api_key is None:
            raise ModelNotConfiguredError(
                "OPENAI_API_KEY is not configured; add it to .env before requesting analysis"
            )

        model_options: dict[str, object] = {
            "api_key": self._settings.openai_api_key.get_secret_value(),
        }
        if self._settings.openai_base_url:
            model_options["base_url"] = self._settings.openai_base_url
        config = AppConfig(
            model_name=self._settings.app_model_name,
            model_options=model_options,
            system_prompt=LEXORA_SYSTEM_PROMPT,
        )
        self._client = AppClient(config)
        return self._client


def _assistant_text_delta(data: Any) -> str:
    if not isinstance(data, list) or not data:
        return ""
    message = data[0]
    if not isinstance(message, dict) or message.get("type") not in {
        "AIMessageChunk",
        "ai",
    }:
        return ""
    return _message_text(message.get("content"))


def _final_assistant_text(values: Any) -> str:
    if not isinstance(values, dict) or not isinstance(values.get("messages"), list):
        return ""
    for message in reversed(values["messages"]):
        if isinstance(message, dict) and message.get("type") in {"AIMessage", "ai"}:
            text = _message_text(message.get("content"))
            if text:
                return text
    return ""


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )
