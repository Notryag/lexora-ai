from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

from agent_platform.application import (
    AgentRunService,
    CommandSubmissionService,
    ConversationService,
)
from agent_platform.core import (
    ActiveThreadRunError,
    ConversationMessage,
    ConversationRole,
    PresentationEnvelope,
    UserContext,
)
from sqlalchemy.exc import IntegrityError

from lexora_ai.application.errors import CaseNotFoundError, RunCancelledError
from lexora_ai.application.ports import (
    CaseLawKnowledgePort,
    ConversationCaseLawChunk,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    EmbeddingGateway,
    LegalConversationGateway,
    LegalKnowledgePort,
    RunStreamBridge,
    TextDeltaSink,
)
from lexora_ai.application.run_journal import (
    ProjectedRunEvent,
    RunJournal,
    live_activity_payload,
)
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import (
    CaseConversationMessage,
    CaseConversationTurnRequest,
    CaseConversationTurnResult,
    CaseLawCitation,
    CaseMaterial,
    CaseProfile,
    CaseProfilePatch,
    CaseProfileUpdate,
    ConversationTurnRequest,
    LegalCitation,
)
from lexora_ai.material_context import MaterialContextChunk, rank_material_context

logger = logging.getLogger(__name__)

AUTHORITY_REFERENCE_PATTERN = re.compile(
    r"\[(?P<square>(?:L[A-Za-z0-9-]+:C\d+|C[A-Za-z0-9-]+:S\d+))\]"
    r"|【(?P<fullwidth>(?:L[A-Za-z0-9-]+:C\d+|C[A-Za-z0-9-]+:S\d+))】"
)
_MAX_PENDING_AUTHORITY_REFERENCE_CHARS = 160
CitationChunk = TypeVar("CitationChunk")


class _AuthorityReferenceDeltaFilter:
    """Remove unknown authority markers without buffering ordinary response text."""

    def __init__(self, available_references: Callable[[], set[str]]) -> None:
        self._available_references = available_references
        self._pending = ""

    def feed(self, delta: str) -> str:
        self._pending += delta
        emitted: list[str] = []
        while self._pending:
            openings = [
                position
                for marker in ("[", "【")
                if (position := self._pending.find(marker)) >= 0
            ]
            if not openings:
                emitted.append(self._pending)
                self._pending = ""
                break
            opening = min(openings)
            if opening:
                emitted.append(self._pending[:opening])
                self._pending = self._pending[opening:]
            if len(self._pending) == 1:
                break
            if self._pending[1] not in {"L", "C"}:
                emitted.append(self._pending[0])
                self._pending = self._pending[1:]
                continue
            closing_marker = "]" if self._pending[0] == "[" else "】"
            closing = self._pending.find(closing_marker, 2)
            if closing < 0:
                if len(self._pending) > _MAX_PENDING_AUTHORITY_REFERENCE_CHARS:
                    emitted.append(self._pending[0])
                    self._pending = self._pending[1:]
                    continue
                break
            candidate = self._pending[: closing + 1]
            match = AUTHORITY_REFERENCE_PATTERN.fullmatch(candidate)
            reference = _authority_reference(match) if match is not None else None
            if reference in self._available_references():
                emitted.append(f"[{reference}]")
            elif match is None:
                emitted.append(candidate)
            self._pending = self._pending[closing + 1 :]
        return "".join(emitted)

    def flush(self) -> str:
        pending = self._pending
        self._pending = ""
        return pending


class _AgentControlledCaseMemory:
    def __init__(self, profile: CaseProfile) -> None:
        self._initial = profile.model_copy(deep=True)
        self.profile = profile.model_copy(deep=True)

    @property
    def updated(self) -> bool:
        return self.profile != self._initial

    async def get_profile(self) -> CaseProfile:
        return self.profile.model_copy(deep=True)

    async def update_profile(self, patch: CaseProfilePatch) -> CaseProfile:
        self.profile = patch.apply(self.profile)
        return self.profile.model_copy(deep=True)


class _AgentControlledRetrieval:
    def __init__(
        self,
        *,
        query_context: str,
        material_chunks: list[MaterialContextChunk],
        embedding_gateway: EmbeddingGateway | None,
        legal_knowledge: LegalKnowledgePort | None,
        case_law_knowledge: CaseLawKnowledgePort | None,
    ) -> None:
        self._query_context = query_context
        self._material_chunks = material_chunks
        self._embedding_gateway = embedding_gateway
        self._legal_knowledge = legal_knowledge
        self._case_law_knowledge = case_law_knowledge
        self._embedding_cache: dict[
            str, tuple[tuple[float, ...] | None, str | None]
        ] = {}
        self.evidence: dict[str, ConversationEvidenceChunk] = {}
        self.legal_authorities: dict[str, ConversationLegalChunk] = {}
        self.case_law_authorities: dict[str, ConversationCaseLawChunk] = {}

    async def _embedding(
        self, query: str
    ) -> tuple[tuple[float, ...] | None, str | None]:
        query = query.strip()
        if not query:
            raise ValueError("retrieval query cannot be blank")
        if query in self._embedding_cache:
            return self._embedding_cache[query]
        query_embedding: tuple[float, ...] | None = None
        embedding_model: str | None = None
        if self._embedding_gateway is not None:
            try:
                query_embedding = await self._embedding_gateway.embed_query(query)
                embedding_model = self._embedding_gateway.model_name
            except Exception:
                logger.warning(
                    "Query embedding failed; falling back to lexical retrieval",
                    exc_info=True,
                )
        result = query_embedding, embedding_model
        self._embedding_cache[query] = result
        return result

    async def search_materials(
        self, query: str
    ) -> tuple[ConversationEvidenceChunk, ...]:
        query_embedding, embedding_model = await self._embedding(query)
        evidence = tuple(
            ConversationEvidenceChunk(
                reference=chunk.reference,
                material_id=chunk.material_id,
                title=chunk.title,
                kind=chunk.kind,
                source_note=chunk.source_note,
                content=chunk.content,
            )
            for chunk in rank_material_context(
                query,
                self._material_chunks,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
            )
        )
        self.evidence.update((chunk.reference, chunk) for chunk in evidence)
        return evidence

    async def search_legal_authorities(
        self, query: str
    ) -> tuple[ConversationLegalChunk, ...]:
        query_embedding, embedding_model = await self._embedding(query)
        authority_query = " ".join(
            part for part in (self._query_context, query) if part
        )
        legal_chunks = (
            await self._legal_knowledge.search(
                authority_query,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
            )
            if self._legal_knowledge is not None
            else []
        )
        legal_authorities = tuple(
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
        )
        self.legal_authorities.update(
            (chunk.reference, chunk) for chunk in legal_authorities
        )
        return legal_authorities

    async def search_case_law(
        self, query: str
    ) -> tuple[ConversationCaseLawChunk, ...]:
        query_embedding, embedding_model = await self._embedding(query)
        authority_query = " ".join(
            part for part in (self._query_context, query) if part
        )
        case_law_chunks = (
            await self._case_law_knowledge.search(
                authority_query,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
            )
            if self._case_law_knowledge is not None
            else []
        )
        case_law_authorities = tuple(
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
        )
        self.case_law_authorities.update(
            (chunk.reference, chunk) for chunk in case_law_authorities
        )
        return case_law_authorities


class PersistentLegalConversationService:
    def __init__(
        self,
        session_factory: SessionFactory,
        context: UserContext,
        gateway: LegalConversationGateway,
        embedding_gateway: EmbeddingGateway | None = None,
        legal_knowledge: LegalKnowledgePort | None = None,
        case_law_knowledge: CaseLawKnowledgePort | None = None,
        stream_bridge: RunStreamBridge | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._gateway = gateway
        self._embedding_gateway = embedding_gateway
        self._legal_knowledge = legal_knowledge
        self._case_law_knowledge = case_law_knowledge
        self._stream_bridge = stream_bridge

    async def execute(
        self,
        case_id: UUID,
        request: CaseConversationTurnRequest,
        *,
        on_text_delta: TextDeltaSink | None = None,
        on_run_started: Callable[[UUID], Awaitable[None]] | None = None,
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
            checkpoint = await unit_of_work.threads.get_runtime_checkpoint(
                self._context, thread.id
            )
            runtime_thread_id = checkpoint[0] if checkpoint is not None else None
            checkpoint_id = checkpoint[1] if checkpoint is not None else None
            previous_messages = (
                await ConversationService(unit_of_work).list_messages(
                    self._context,
                    thread.id,
                )
                if checkpoint_id is None
                else []
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
        run_key = str(submission.run_id)
        if on_run_started is not None:
            await on_run_started(submission.run_id)
        if self._stream_bridge is not None:
            await _publish_stream_event(
                self._stream_bridge,
                run_key,
                "metadata",
                {"run_id": run_key, "thread_id": str(thread.id)},
            )

        async def publish_activity(event: object) -> None:
            if self._stream_bridge is None or not isinstance(event, ProjectedRunEvent):
                return
            await _publish_stream_event(
                self._stream_bridge,
                run_key,
                "custom",
                live_activity_payload(event),
            )

        run_journal = RunJournal(
            self._session_factory,
            self._context,
            thread_id=thread.id,
            run_id=submission.run_id,
            on_event=publish_activity,
        )
        history = tuple(
            ConversationContextMessage(role=message.role.value, content=message.content)
            for message in _completed_history(previous_messages)[-20:]
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
        retrieval = _AgentControlledRetrieval(
            query_context=" ".join(
                part
                for part in (case.title, case.profile.retrieval_text())
                if part
            ),
            material_chunks=[
                MaterialContextChunk(
                    reference=chunk.reference,
                    material_id=str(chunk.material_id),
                    title=chunk.title,
                    kind=chunk.kind.value,
                    source_note=chunk.source_note,
                    content=chunk.content,
                    page_start=None,
                    page_end=None,
                    embedding=(
                        tuple(chunk.embedding) if chunk.embedding is not None else None
                    ),
                    embedding_model=chunk.embedding_model,
                )
                for chunk in stored_chunks
            ],
            embedding_gateway=self._embedding_gateway,
            legal_knowledge=self._legal_knowledge,
            case_law_knowledge=self._case_law_knowledge,
        )
        case_memory = _AgentControlledCaseMemory(case.profile)
        try:
            gateway_arguments = {
                "thread_id": runtime_thread_id or submission.run_id,
                "run_id": submission.run_id,
                "checkpoint_id": checkpoint_id,
                "history": history,
                "retrieval": retrieval,
                "case_memory": case_memory,
                "event_sink": run_journal,
            }
            if on_text_delta is None and self._stream_bridge is None:
                generated = await self._gateway.converse(turn, **gateway_arguments)
            else:
                emitted_delta = False
                reference_filter = _AuthorityReferenceDeltaFilter(
                    lambda: {
                        *retrieval.legal_authorities,
                        *retrieval.case_law_authorities,
                    }
                )

                async def emit_delta(delta: str) -> None:
                    nonlocal emitted_delta
                    filtered = reference_filter.feed(delta)
                    if filtered:
                        emitted_delta = True
                        if self._stream_bridge is not None:
                            await _publish_stream_event(
                                self._stream_bridge,
                                run_key,
                                "messages",
                                {"delta": filtered},
                            )
                        if on_text_delta is not None:
                            await on_text_delta(filtered)

                generated = await self._gateway.converse_stream(
                    turn,
                    on_text_delta=emit_delta,
                    **gateway_arguments,
                )
                tail = reference_filter.flush()
                if tail:
                    emitted_delta = True
                    if self._stream_bridge is not None:
                        await _publish_stream_event(
                            self._stream_bridge,
                            run_key,
                            "messages",
                            {"delta": tail},
                        )
                    if on_text_delta is not None:
                        await on_text_delta(tail)
            content = _strip_unavailable_authority_references(
                generated.content,
                {*retrieval.legal_authorities, *retrieval.case_law_authorities},
            )
            if not content.strip():
                raise RuntimeError("conversation provider returned an empty response")
            if (on_text_delta is not None or self._stream_bridge is not None) and not emitted_delta:
                if self._stream_bridge is not None:
                    await _publish_stream_event(
                        self._stream_bridge,
                        run_key,
                        "messages",
                        {"delta": content},
                    )
                if on_text_delta is not None:
                    await on_text_delta(content)
            expected_runtime_thread_id = runtime_thread_id or submission.run_id
            if generated.runtime_thread_id != str(expected_runtime_thread_id):
                raise RuntimeError("conversation provider changed the runtime thread ID")
            legal_citations = [
                LegalCitation(
                    reference=chunk.reference,
                    title=chunk.title,
                    article_label=chunk.article_label,
                    issuing_authority=chunk.issuing_authority,
                    source_url=chunk.source_url,
                    status=chunk.status,
                    content=chunk.content,
                )
                for chunk in _cited_chunks(content, retrieval.legal_authorities)
            ]
            case_law_citations = [
                CaseLawCitation(
                    reference=chunk.reference,
                    case_number=chunk.case_number,
                    title=chunk.title,
                    section_label=chunk.section_label,
                    issuing_authority=chunk.issuing_authority,
                    source_url=chunk.source_url,
                    published_on=chunk.published_on,
                    content=chunk.content,
                )
                for chunk in _cited_chunks(content, retrieval.case_law_authorities)
            ]
            completed = await self._mark_completed(
                run_id=submission.run_id,
                thread_id=thread.id,
                content=content,
                legal_citations=legal_citations,
                case_law_citations=case_law_citations,
                case_id=case_id,
                case_profile=(case_memory.profile if case_memory.updated else None),
                checkpoint_id=generated.runtime_checkpoint_id,
                runtime_thread_id=expected_runtime_thread_id,
                generated_title=generated.runtime_title,
            )
            if not completed:
                raise RunCancelledError("This analysis was cancelled")
            result = CaseConversationTurnResult(
                case_id=case_id,
                thread_id=thread.id,
                run_id=submission.run_id,
                case_title=completed,
                assistant_message=content,
                material_count=len(materials),
                legal_citations=legal_citations,
                case_law_citations=case_law_citations,
                profile_updated=case_memory.updated,
                case_profile=case_memory.profile,
            )
            if self._stream_bridge is not None:
                await _publish_stream_event(
                    self._stream_bridge,
                    run_key,
                    "complete",
                    {"result": result.model_dump(mode="json")},
                )
            return result
        except BaseException as exc:
            await self._mark_failed(submission.run_id, exc)
            if self._stream_bridge is not None:
                await _publish_stream_event(
                    self._stream_bridge,
                    run_key,
                    "error",
                    _run_stream_error_payload(exc),
                )
            raise
        finally:
            if self._stream_bridge is not None:
                await _end_stream(self._stream_bridge, run_key)

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
        case_id: UUID,
        case_profile: CaseProfile | None,
        checkpoint_id: str | None,
        runtime_thread_id: UUID,
        generated_title: str | None,
    ) -> str | None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            runs = AgentRunService(unit_of_work)
            run = await runs.get_run(self._context, run_id)
            if run is None or not await runs.mark_completed(
                self._context,
                run,
                result_message=content,
            ):
                return None
            case = await unit_of_work.cases.get(self._context, case_id)
            if case is None:
                raise CaseNotFoundError("Case not found")
            case_title = case.title
            if generated_title and case.title == "未命名案件":
                updated_case = await unit_of_work.cases.update_title_if(
                    self._context,
                    case_id,
                    expected_title="未命名案件",
                    title=generated_title,
                )
                if updated_case is not None:
                    case_title = updated_case.title
                    thread = await unit_of_work.threads.get_for_case(
                        self._context,
                        case_id,
                    )
                    if thread is not None:
                        await unit_of_work.threads.update_title(
                            self._context,
                            thread.id,
                            updated_case.title,
                        )
            if case_profile is not None:
                updated_case = await unit_of_work.cases.update_profile(
                    self._context,
                    case_id,
                    CaseProfileUpdate.model_validate(case_profile.model_dump(mode="json")),
                )
                if updated_case is None:
                    raise CaseNotFoundError("Case not found")
            if checkpoint_id is not None:
                if not await unit_of_work.threads.update_runtime_checkpoint(
                    self._context,
                    thread_id,
                    runtime_thread_id=runtime_thread_id,
                    checkpoint_id=checkpoint_id,
                ):
                    raise RuntimeError(
                        "Conversation thread disappeared while saving checkpoint"
                    )
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
            return case_title

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


def _completed_history(messages: list[ConversationMessage]) -> list[ConversationMessage]:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == ConversationRole.assistant:
            return messages[: index + 1]
    return []


def _run_stream_error_payload(error: BaseException) -> dict[str, str]:
    error_type = type(error).__name__
    if isinstance(error, RunCancelledError):
        return {
            "code": "run_cancelled",
            "message": "分析已取消。",
            "error_type": error_type,
        }
    if error_type == "ModelTemporarilyUnavailableError":
        return {
            "code": "provider_unavailable",
            "message": str(error),
            "error_type": error_type,
        }
    if error_type == "ModelNotConfiguredError":
        return {
            "code": "request_rejected",
            "message": str(error),
            "error_type": error_type,
        }
    return {
        "code": "run_failed",
        "message": "分析失败，请稍后重试。",
        "error_type": error_type,
    }


async def _publish_stream_event(
    bridge: RunStreamBridge,
    run_id: str,
    event: str,
    data: object,
) -> None:
    try:
        await bridge.publish(run_id, event, data)
    except Exception:
        logger.exception(
            "Lexora stream publication failed",
            extra={"run_id": run_id, "event": event},
        )


async def _end_stream(bridge: RunStreamBridge, run_id: str) -> None:
    try:
        await bridge.publish_end(run_id)
    except Exception:
        logger.exception("Lexora stream termination failed", extra={"run_id": run_id})
        return
    asyncio.create_task(bridge.cleanup(run_id, delay=60))


def _cited_chunks(
    content: str, available: dict[str, CitationChunk]
) -> list[CitationChunk]:
    cited: list[CitationChunk] = []
    seen: set[str] = set()
    for match in AUTHORITY_REFERENCE_PATTERN.finditer(content):
        reference = _authority_reference(match)
        if reference in seen or reference not in available:
            continue
        seen.add(reference)
        cited.append(available[reference])
    return cited


def _strip_unavailable_authority_references(
    content: str, available_references: set[str]
) -> str:
    return AUTHORITY_REFERENCE_PATTERN.sub(
        lambda match: (
            f"[{_authority_reference(match)}]"
            if _authority_reference(match) in available_references
            else ""
        ),
        content,
    )


def _authority_reference(match: re.Match[str]) -> str:
    return match.group("square") or match.group("fullwidth")
