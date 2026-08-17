from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage
from north import (
    AppClient,
    AppConfig,
    MemoryStreamBridge,
    RunExecutor,
    RuntimeEventSink,
    RuntimeStreamEvent,
    build_agent,
)
from north.runtime import RunManager, StreamBridge
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from lexora_ai.application import (
    CaseContextService,
    ConversationCaseLawChunk,
    ConversationCaseMemoryPort,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    ConversationRetrievalPort,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
)
from lexora_ai.application.ports import TextDeltaSink
from lexora_ai.config import Settings
from lexora_ai.domain import CaseAnalysisRequest, ConversationTurnRequest
from lexora_ai.infrastructure.agent_plugins import build_lexora_plugins
from lexora_ai.infrastructure.case_analyst import build_case_analyst_definition
from lexora_ai.infrastructure.legal_researcher import (
    build_legal_researcher_definition,
    partition_legal_research_tools,
)
from lexora_ai.infrastructure.north_tools import build_lexora_tools
from lexora_ai.prompts import (
    LEXORA_SYSTEM_PROMPT,
    build_case_analysis_prompt,
    build_conversation_case_data,
    build_specialist_task_input,
    render_conversation_prompt,
)


class ModelNotConfiguredError(RuntimeError):
    pass


class ModelTemporarilyUnavailableError(RuntimeError):
    pass


class NorthCaseAnalysisGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        checkpointer=None,
        stream_bridge: StreamBridge | None = None,
    ) -> None:
        self._settings = settings
        self._checkpointer = checkpointer
        self._stream_bridge = stream_bridge or MemoryStreamBridge()
        self._client: AppClient | None = None

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
            raise ModelTemporarilyUnavailableError("模型服务暂时不可用，请稍后重试。") from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelTemporarilyUnavailableError("模型服务暂时不可用，请稍后重试。") from exc
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
        event_sink: RuntimeEventSink | None = None,
    ) -> GeneratedConversationTurn:
        async def discard_delta(_delta: str) -> None:
            return None

        return await self._run_conversation(
            request,
            thread_id=thread_id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            on_text_delta=discard_delta,
            history=history,
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval=retrieval,
            case_memory=case_memory,
            event_sink=event_sink,
        )

    async def converse_stream(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        run_id: UUID | None = None,
        checkpoint_id: str | None = None,
        on_text_delta: TextDeltaSink,
        history: tuple[ConversationContextMessage, ...] = (),
        evidence: tuple[ConversationEvidenceChunk, ...] | None = None,
        legal_authorities: tuple[ConversationLegalChunk, ...] = (),
        case_law_authorities: tuple[ConversationCaseLawChunk, ...] = (),
        retrieval: ConversationRetrievalPort | None = None,
        case_memory: ConversationCaseMemoryPort | None = None,
        event_sink: RuntimeEventSink | None = None,
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
            event_sink=event_sink,
        )

    async def _run_conversation(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
        run_id: UUID | None,
        checkpoint_id: str | None,
        on_text_delta: TextDeltaSink,
        history: tuple[ConversationContextMessage, ...],
        evidence: tuple[ConversationEvidenceChunk, ...] | None,
        legal_authorities: tuple[ConversationLegalChunk, ...],
        case_law_authorities: tuple[ConversationCaseLawChunk, ...],
        retrieval: ConversationRetrievalPort | None,
        case_memory: ConversationCaseMemoryPort | None,
        event_sink: RuntimeEventSink | None,
    ) -> GeneratedConversationTurn:
        case_data = build_conversation_case_data(
            request,
            history=(),
            evidence=evidence,
            legal_authorities=legal_authorities,
            case_law_authorities=case_law_authorities,
            retrieval_available=retrieval is not None,
            case_memory_available=case_memory is not None,
        )
        prompt = render_conversation_prompt(case_data)

        def specialist_input(task: str, _runtime: object) -> str:
            return build_specialist_task_input(task, case_data)

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
                await on_text_delta(delta)

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
            all_tools = build_lexora_tools(retrieval)
            supervisor_tools, research_tools = partition_legal_research_tools(all_tools)
            case_context = CaseContextService(
                case_memory,
                jurisdiction=self._settings.legal_jurisdiction,
            )
            definitions = [
                build_case_analyst_definition(
                    result_processor=lambda result, _runtime: case_context.process(result),
                    input_builder=specialist_input,
                )
            ]
            if research_tools:
                definitions.append(
                    build_legal_researcher_definition(
                        research_tools,
                        input_builder=specialist_input,
                    )
                )
            plugins = build_lexora_plugins(
                supervisor_tools=supervisor_tools,
                definitions=definitions,
            )
            result = await RunExecutor(self._stream_bridge, manager).execute(
                record,
                agent_factory=lambda: build_agent(
                    self._get_config(),
                    plugins=plugins,
                    checkpointer=self._checkpointer,
                ),
                graph_input={"messages": graph_messages},
                config={
                    "configurable": configurable,
                    "recursion_limit": self._get_config().recursion_limit,
                },
                context={"thread_id": resolved_thread_id, "run_id": resolved_run_id},
                stream_observer=observe,
                event_sink=event_sink,
                publish_modes=(),
                publish_lifecycle=False,
            )
        except (APIConnectionError, APITimeoutError, RateLimitError) as exc:
            raise ModelTemporarilyUnavailableError("模型服务暂时不可用，请稍后重试。") from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelTemporarilyUnavailableError("模型服务暂时不可用，请稍后重试。") from exc
            raise
        content = _final_assistant_text(result.values)
        if not content:
            raise RuntimeError("North did not return an assistant message")
        return GeneratedConversationTurn(
            content=content,
            runtime_thread_id=resolved_thread_id,
            runtime_checkpoint_id=await self._latest_checkpoint_id(resolved_thread_id),
            runtime_title=_runtime_title(result.values),
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


def _runtime_title(values: Any) -> str | None:
    if not isinstance(values, dict):
        return None
    title = values.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


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
