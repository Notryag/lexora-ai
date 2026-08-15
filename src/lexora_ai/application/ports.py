from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from lexora_ai.domain import (
    CaseAnalysisRequest,
    CaseFactorProfile,
    CaseLawChunk,
    CaseProfile,
    CaseProfilePatch,
    ConversationTurnRequest,
    LegalKnowledgeChunk,
    LegalTurnFollowUpReview,
    LegalTurnPreparation,
)


@dataclass(frozen=True, slots=True)
class GeneratedCaseAnalysis:
    content: str
    runtime_thread_id: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedConversationTurn:
    content: str
    runtime_thread_id: str
    runtime_checkpoint_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationContextMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ConversationEvidenceChunk:
    reference: str
    material_id: str
    title: str
    kind: str
    source_note: str | None
    content: str


@dataclass(frozen=True, slots=True)
class ConversationLegalChunk:
    reference: str
    title: str
    article_label: str | None
    issuing_authority: str
    source_url: str
    status: str
    content: str


@dataclass(frozen=True, slots=True)
class ConversationCaseLawChunk:
    reference: str
    case_number: str
    title: str
    section_label: str
    issuing_authority: str
    source_url: str
    published_on: str | None
    content: str


class ConversationRetrievalPort(Protocol):
    async def search_materials(self, query: str) -> tuple[ConversationEvidenceChunk, ...]: ...

    async def search_legal_authorities(
        self, query: str
    ) -> tuple[ConversationLegalChunk, ...]: ...

    async def search_case_law(
        self, query: str
    ) -> tuple[ConversationCaseLawChunk, ...]: ...


class ConversationCaseMemoryPort(Protocol):
    async def get_profile(self) -> CaseProfile: ...

    async def update_profile(self, patch: CaseProfilePatch) -> CaseProfile: ...


class FollowUpReviewerPort(Protocol):
    async def review(
        self,
        *,
        user_message: str,
        preparation: LegalTurnPreparation,
        factor_profile: CaseFactorProfile,
    ) -> list[LegalTurnFollowUpReview]: ...


class CaseAnalysisGateway(Protocol):
    async def analyze(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID,
    ) -> GeneratedCaseAnalysis: ...


class LegalConversationGateway(Protocol):
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
    ) -> GeneratedConversationTurn: ...

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
    ) -> GeneratedConversationTurn: ...


class EmbeddingGateway(Protocol):
    @property
    def model_name(self) -> str: ...

    async def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]: ...

    async def embed_query(self, text: str) -> tuple[float, ...]: ...


class LegalKnowledgePort(Protocol):
    async def search(
        self,
        query: str,
        *,
        query_embedding: tuple[float, ...] | None,
        embedding_model: str | None,
        top_k: int = 6,
    ) -> list[LegalKnowledgeChunk]: ...


class CaseLawKnowledgePort(Protocol):
    async def search(
        self,
        query: str,
        *,
        query_embedding: tuple[float, ...] | None,
        embedding_model: str | None,
        top_k: int = 5,
    ) -> list[CaseLawChunk]: ...
