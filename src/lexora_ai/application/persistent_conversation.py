from __future__ import annotations

import logging
from uuid import UUID

from agent_platform.application import (
    AgentRunService,
    CommandSubmissionService,
    ConversationService,
)
from agent_platform.core import ActiveThreadRunError, PresentationEnvelope, UserContext
from sqlalchemy.exc import IntegrityError

from lexora_ai.application.errors import CaseNotFoundError
from lexora_ai.application.ports import (
    CaseLawKnowledgePort,
    ConversationCaseLawChunk,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    EmbeddingGateway,
    LegalConversationGateway,
    LegalKnowledgePort,
)
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import (
    CaseConversationMessage,
    CaseConversationTurnRequest,
    CaseConversationTurnResult,
    CaseLawCitation,
    CaseMaterial,
    ConversationTurnRequest,
    LegalCitation,
)
from lexora_ai.material_context import MaterialContextChunk, rank_material_context

logger = logging.getLogger(__name__)


class PersistentLegalConversationService:
    def __init__(
        self,
        session_factory: SessionFactory,
        context: UserContext,
        gateway: LegalConversationGateway,
        embedding_gateway: EmbeddingGateway | None = None,
        legal_knowledge: LegalKnowledgePort | None = None,
        case_law_knowledge: CaseLawKnowledgePort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._gateway = gateway
        self._embedding_gateway = embedding_gateway
        self._legal_knowledge = legal_knowledge
        self._case_law_knowledge = case_law_knowledge

    async def execute(
        self,
        case_id: UUID,
        request: CaseConversationTurnRequest,
    ) -> CaseConversationTurnResult:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            case = await unit_of_work.cases.get(self._context, case_id)
            if case is None:
                raise CaseNotFoundError("Case not found")
            materials = await unit_of_work.cases.list_materials(self._context, case_id)
            stored_chunks = await unit_of_work.cases.list_material_chunks(self._context, case_id)
            thread = await unit_of_work.threads.get_or_create_for_case(
                self._context,
                case_id=case_id,
                title=case.title,
            )
            active_run = await unit_of_work.runs.get_active_for_thread(
                self._context,
                thread.id,
            )
            if active_run is not None:
                raise ActiveThreadRunError("This case already has an active analysis")
            previous_messages = await unit_of_work.messages.list_for_thread(
                self._context,
                thread.id,
            )
            try:
                submission = await CommandSubmissionService(unit_of_work).submit(
                    self._context,
                    input_message=request.message,
                    thread_id=thread.id,
                )
            except IntegrityError:
                active_run = await unit_of_work.runs.get_active_for_thread(
                    self._context,
                    thread.id,
                )
                if active_run is not None:
                    raise ActiveThreadRunError(
                        "This case already has an active analysis"
                    ) from None
                raise

        await self._mark_running(submission.run_id)
        history = tuple(
            ConversationContextMessage(role=message.role.value, content=message.content)
            for message in previous_messages[-20:]
        )
        turn = ConversationTurnRequest(
            thread_id=thread.id,
            message=request.message,
            case_title=case.title,
            case_profile=case.profile,
            materials=[
                CaseMaterial(
                    material_id=material.material_id,
                    title=material.title,
                    kind=material.kind,
                    content=material.content,
                    source_note=material.source_note,
                )
                for material in materials
            ],
        )
        try:
            query_embedding: tuple[float, ...] | None = None
            embedding_model: str | None = None
            if self._embedding_gateway is not None:
                try:
                    query_embedding = await self._embedding_gateway.embed_query(request.message)
                    embedding_model = self._embedding_gateway.model_name
                except Exception:
                    logger.warning(
                        "Query embedding failed; falling back to lexical retrieval",
                        exc_info=True,
                    )
            retrieved_chunks = rank_material_context(
                request.message,
                [
                    MaterialContextChunk(
                        reference=chunk.reference,
                        material_id=str(chunk.material_id),
                        title=chunk.title,
                        kind=chunk.kind.value,
                        source_note=chunk.source_note,
                        content=chunk.content,
                        page_start=None,
                        page_end=None,
                        embedding=(tuple(chunk.embedding) if chunk.embedding is not None else None),
                        embedding_model=chunk.embedding_model,
                    )
                    for chunk in stored_chunks
                ],
                query_embedding=query_embedding,
                embedding_model=embedding_model,
            )
            legal_chunks = (
                await self._legal_knowledge.search(
                    " ".join(
                        part
                        for part in (
                            case.title,
                            case.profile.retrieval_text(),
                            request.message,
                        )
                        if part
                    ),
                    query_embedding=query_embedding,
                    embedding_model=embedding_model,
                )
                if self._legal_knowledge is not None
                else []
            )
            legal_citations = [
                LegalCitation(
                    reference=chunk.reference,
                    title=chunk.title,
                    article_label=chunk.article_label,
                    issuing_authority=chunk.issuing_authority,
                    source_url=chunk.source_url,
                    status=chunk.status,
                )
                for chunk in legal_chunks
            ]
            case_law_chunks = (
                await self._case_law_knowledge.search(
                    " ".join(
                        part
                        for part in (
                            case.title,
                            case.profile.retrieval_text(),
                            request.message,
                        )
                        if part
                    ),
                    query_embedding=query_embedding,
                    embedding_model=embedding_model,
                )
                if self._case_law_knowledge is not None
                else []
            )
            case_law_citations: list[CaseLawCitation] = []
            cited_case_sources: set[UUID] = set()
            for chunk in case_law_chunks:
                if chunk.source_id in cited_case_sources:
                    continue
                cited_case_sources.add(chunk.source_id)
                case_law_citations.append(
                    CaseLawCitation(
                        reference=chunk.reference,
                        case_number=chunk.case_number,
                        title=chunk.title,
                        section_label=chunk.section_label,
                        issuing_authority=chunk.issuing_authority,
                        source_url=chunk.source_url,
                        published_on=chunk.published_on,
                    )
                )
            generated = await self._gateway.converse(
                turn,
                thread_id=submission.run_id,
                history=history,
                evidence=tuple(
                    ConversationEvidenceChunk(
                        reference=chunk.reference,
                        material_id=chunk.material_id,
                        title=chunk.title,
                        kind=chunk.kind,
                        source_note=chunk.source_note,
                        content=chunk.content,
                    )
                    for chunk in retrieved_chunks
                ),
                legal_authorities=tuple(
                    ConversationLegalChunk(
                        reference=chunk.reference,
                        title=chunk.title,
                        article_label=chunk.article_label,
                        issuing_authority=chunk.issuing_authority,
                        source_url=chunk.source_url,
                        status=chunk.status.value,
                        content=chunk.content,
                    )
                    for chunk in legal_chunks
                ),
                case_law_authorities=tuple(
                    ConversationCaseLawChunk(
                        reference=chunk.reference,
                        case_number=chunk.case_number,
                        title=chunk.title,
                        section_label=chunk.section_label,
                        issuing_authority=chunk.issuing_authority,
                        source_url=chunk.source_url,
                        published_on=(
                            chunk.published_on.isoformat() if chunk.published_on else None
                        ),
                        content=chunk.content,
                    )
                    for chunk in case_law_chunks
                ),
            )
            content = generated.content.strip()
            if not content:
                raise RuntimeError("conversation provider returned an empty response")
            await self._mark_completed(
                run_id=submission.run_id,
                thread_id=thread.id,
                content=content,
                legal_citations=legal_citations,
                case_law_citations=case_law_citations,
            )
        except BaseException as exc:
            await self._mark_failed(submission.run_id, exc)
            raise

        return CaseConversationTurnResult(
            case_id=case_id,
            thread_id=thread.id,
            run_id=submission.run_id,
            assistant_message=content,
            material_count=len(materials),
            legal_citations=legal_citations,
            case_law_citations=case_law_citations,
        )

    async def list_messages(self, case_id: UUID) -> list[CaseConversationMessage]:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            case = await unit_of_work.cases.get(self._context, case_id)
            if case is None:
                raise CaseNotFoundError("Case not found")
            thread = await unit_of_work.threads.get_or_create_for_case(
                self._context,
                case_id=case_id,
                title=case.title,
            )
            messages = await ConversationService(unit_of_work).list_messages(
                self._context,
                thread.id,
            )
            await unit_of_work.commit()
            return [
                CaseConversationMessage(
                    id=message.id,
                    thread_id=message.thread_id,
                    run_id=message.run_id,
                    role=message.role.value,
                    content=message.content,
                    legal_citations=[
                        LegalCitation.model_validate(citation)
                        for citation in self._citation_payload(message).get(
                            "legal_citations", []
                        )
                    ],
                    case_law_citations=[
                        CaseLawCitation.model_validate(citation)
                        for citation in self._citation_payload(message).get(
                            "case_law_citations", []
                        )
                    ],
                    created_at=message.created_at,
                )
                for message in messages
            ]


    async def _mark_running(self, run_id: UUID) -> None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            runs = AgentRunService(unit_of_work)
            run = await runs.get_run(self._context, run_id)
            if run is None or not await runs.mark_running(self._context, run):
                raise RuntimeError("failed to start persisted run")
            await unit_of_work.commit()

    async def _mark_completed(
        self,
        *,
        run_id: UUID,
        thread_id: UUID,
        content: str,
        legal_citations: list[LegalCitation],
        case_law_citations: list[CaseLawCitation],
    ) -> None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            runs = AgentRunService(unit_of_work)
            run = await runs.get_run(self._context, run_id)
            if run is None or not await runs.mark_completed(
                self._context,
                run,
                result_message=content,
            ):
                raise RuntimeError("failed to complete persisted run")
            await ConversationService(unit_of_work).upsert_assistant_message(
                self._context,
                thread_id=thread_id,
                run_id=run_id,
                content=content,
                presentation=PresentationEnvelope(
                    kind="lexora_authority_citations",
                    schema_version=2,
                    payload={
                        "legal_citations": [
                            citation.model_dump(mode="json") for citation in legal_citations
                        ],
                        "case_law_citations": [
                            citation.model_dump(mode="json")
                            for citation in case_law_citations
                        ],
                    },
                ),
            )
            await unit_of_work.commit()

    @staticmethod
    def _citation_payload(message: object) -> dict[str, object]:
        presentation = getattr(message, "presentation", None)
        if presentation is None or presentation.kind not in {
            "lexora_legal_citations",
            "lexora_authority_citations",
        }:
            return {}
        return presentation.payload

    async def _mark_failed(self, run_id: UUID, error: BaseException) -> None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            runs = AgentRunService(unit_of_work)
            run = await runs.get_run(self._context, run_id)
            if run is not None:
                await runs.mark_failed(
                    self._context,
                    run,
                    error_type=type(error).__name__,
                    error_message=str(error)[:4000] or "conversation failed",
                )
                await unit_of_work.commit()
