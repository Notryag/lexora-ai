from __future__ import annotations

import asyncio
from uuid import UUID

from north import AppClient, AppConfig

from lexora_ai.application import (
    ConversationCaseLawChunk,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
)
from lexora_ai.config import Settings
from lexora_ai.domain import CaseAnalysisRequest, ConversationTurnRequest
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
    ) -> GeneratedConversationTurn:
        client = self._get_client()
        response = await asyncio.to_thread(
            client.chat,
            build_conversation_prompt(
                request,
                history=history,
                evidence=evidence,
                legal_authorities=legal_authorities,
                case_law_authorities=case_law_authorities,
            ),
            thread_id=str(thread_id),
        )
        if response.thread_id is None:
            raise RuntimeError("North did not return a conversation thread ID")
        return GeneratedConversationTurn(
            content=str(response),
            runtime_thread_id=response.thread_id,
        )


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
