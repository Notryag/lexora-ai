from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage
from north import (
    AppClient,
    AppConfig,
    MemoryStreamBridge,
    RunExecutor,
    RuntimeStreamEvent,
    build_agent,
)
from north.runtime import RunManager
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from lexora_ai.application import (
    ConversationCaseLawChunk,
    ConversationCaseMemoryPort,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    ConversationRetrievalPort,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
)
from lexora_ai.config import Settings
from lexora_ai.domain import CaseAnalysisRequest, ConversationTurnRequest
from lexora_ai.infrastructure.follow_up_reviewer import NorthFollowUpReviewer
from lexora_ai.infrastructure.legal_turn_middleware import (
    LegalTurnPreparationMiddleware,
)
from lexora_ai.infrastructure.north_tools import build_lexora_tools
from lexora_ai.prompts import (
    LEXORA_SYSTEM_PROMPT,
    build_case_analysis_prompt,
    build_conversation_prompt,
)


class ModelNotConfiguredError(RuntimeError):
    pass


class ModelTemporarilyUnavailableError(RuntimeError):
    pass


class NorthCaseAnalysisGateway:
    def __init__(self, settings: Settings, *, checkpointer=None) -> None:
        self._settings = settings
        self._checkpointer = checkpointer
        self._client: AppClient | None = None
        self._follow_up_reviewer = NorthFollowUpReviewer(settings)

    async def analyze(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID,
    ) -> GeneratedCaseAnalysis:
        client = self._get_client()
        try:
            response = await asyncio.to_thread(
                client.chat,
                build_case_analysis_prompt(request),
                thread_id=str(analysis_id),
            )
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise ModelTemporarilyUnavailableError(
                "模型服务暂时不可用，请稍后重试。"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelTemporarilyUnavailableError(
                    "模型服务暂时不可用，请稍后重试。"
                ) from exc
            raise
        return GeneratedCaseAnalysis(
            content=str(response),
            runtime_thread_id=response.thread_id,
        )

    async def converse(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        run_id: UUID | None = None,
        checkpoint_id: str | None = None,
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval: ConversationRetrievalPort | None = None,
        case_memory: ConversationCaseMemoryPort | None = None,
    ) -> GeneratedConversationTurn:
        return await self._run_conversation(
            request,
            thread_id=thread_id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            on_text_delta=lambda _delta: None,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval=retrieval,
            case_memory=case_memory,
        )

    async def converse_stream(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        run_id: UUID | None = None,
        checkpoint_id: str | None = None,
        on_text_delta: Callable[[str], None],
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval: ConversationRetrievalPort | None = None,
        case_memory: ConversationCaseMemoryPort | None = None,
    ) -> GeneratedConversationTurn:
        return await self._run_conversation(
            request,
            thread_id=thread_id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            on_text_delta=on_text_delta,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval=retrieval,
            case_memory=case_memory,
        )

    async def _run_conversation(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        run_id: UUID | None,
        checkpoint_id: str | None,
        on_text_delta: Callable[[str], None],
        history: tuple[ConversationContextMessage, ...],
        evidence: tuple[ConversationEvidenceChunk, ...] | None,
        legal_authorities: tuple[ConversationLegalChunk, ...],
        case_law_authorities: tuple[ConversationCaseLawChunk, ...],
        retrieval: ConversationRetrievalPort | None,
        case_memory: ConversationCaseMemoryPort | None,
    ) -> GeneratedConversationTurn:
        prompt = build_conversation_prompt(
            request,
            history=(),
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval_available=retrieval is not None,
            case_memory_available=case_memory is not None,
        )
        resolved_thread_id = str(thread_id)
        resolved_run_id = str(run_id or thread_id)
        manager = RunManager()
        record = manager.create(
            thread_id=resolved_thread_id,
            run_id=resolved_run_id,
        )

        async def observe(event: RuntimeStreamEvent) -> None:
            if event.mode != "messages" or event.namespace:
                return
            delta = _assistant_text_delta(event.data)
            if delta:
                on_text_delta(delta)

        graph_messages = []
        if checkpoint_id is None:
            graph_messages.extend(
                AIMessage(content=message.content)
                if message.role == "assistant"
                else HumanMessage(content=message.content)
                for message in history
            )
        graph_messages.append(HumanMessage(content=prompt))
        configurable = {"thread_id": resolved_thread_id}
        if checkpoint_id is not None:
            configurable["checkpoint_id"] = checkpoint_id
        try:
            result = await RunExecutor(MemoryStreamBridge(), manager).execute(
                record,
                agent_factory=lambda: build_agent(
                    self._get_config(),
                    tools=build_lexora_tools(
                        retrieval,
                        case_memory,
                        user_message=request.message,
                        jurisdiction=self._settings.legal_jurisdiction,
                        follow_up_reviewer=self._follow_up_reviewer,
                        factor_update_reviewer=self._follow_up_reviewer,
                    ),
                    additional_middlewares=[LegalTurnPreparationMiddleware()],
                    checkpointer=self._checkpointer,
                ),
                graph_input={"messages": graph_messages},
                config={
                    "configurable": configurable,
                    "recursion_limit": self._get_config().recursion_limit,
                },
                context={"thread_id": resolved_thread_id, "run_id": resolved_run_id},
                stream_observer=observe,
                publish_modes=(),
            )
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise ModelTemporarilyUnavailableError(
                "模型服务暂时不可用，请稍后重试。"
            ) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelTemporarilyUnavailableError(
                    "模型服务暂时不可用，请稍后重试。"
                ) from exc
            raise
        content = _final_assistant_text(result.values)
        if not content:
            raise RuntimeError("North did not return an assistant message")
        return GeneratedConversationTurn(
            content=content,
            runtime_thread_id=resolved_thread_id,
            runtime_checkpoint_id=await self._latest_checkpoint_id(resolved_thread_id),
        )

    async def _latest_checkpoint_id(
        self,
        thread_id: str,
    ) -> str | None:
        if self._checkpointer is None:
            return None
        checkpoint = await self._checkpointer.aget_tuple(
            {
                "configurable": {
                    "thread_id": thread_id,
                }
            }
        )
        if checkpoint is None:
            raise RuntimeError("North completed without persisting a checkpoint")
        configurable = checkpoint.config.get("configurable", {})
        checkpoint_id = configurable.get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id:
            raise RuntimeError("Persisted checkpoint has no checkpoint_id")
        return checkpoint_id

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
