from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from lexora_ai.application.errors import (
    CaseLawSourceNotFoundError,
    DuplicateCaseLawSourceError,
    EmbeddingUnavailableError,
)
from lexora_ai.application.ports import EmbeddingGateway
from lexora_ai.case_law_context import split_case_law
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import (
    CaseLawSourceCreate,
    CaseLawSourceDetail,
    CaseLawSourceSummary,
    CaseLawSourceUpdate,
)


class CaseLawSourceService:
    def __init__(
        self,
        session_factory: SessionFactory,
        embedding_gateway: EmbeddingGateway | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_gateway = embedding_gateway

    async def create(self, request: CaseLawSourceCreate) -> CaseLawSourceDetail:
        source_id = uuid4()
        chunks = split_case_law(source_id, request.title, request.content)
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            try:
                result = await unit_of_work.case_law.create(
                    request,
                    chunks,
                    source_id=source_id,
                )
                await unit_of_work.commit()
                return result
            except IntegrityError as exc:
                await unit_of_work.rollback()
                raise DuplicateCaseLawSourceError(
                    "this official case-law source version has already been imported"
                ) from exc

    async def list(self) -> list[CaseLawSourceSummary]:
        async with self._session_factory() as session:
            return await LexoraUnitOfWork(session).case_law.list()

    async def get(self, source_id: UUID) -> CaseLawSourceDetail:
        async with self._session_factory() as session:
            result = await LexoraUnitOfWork(session).case_law.get(source_id)
            if result is None:
                raise CaseLawSourceNotFoundError("Case-law source not found")
            return result

    async def update(
        self,
        source_id: UUID,
        request: CaseLawSourceUpdate,
    ) -> CaseLawSourceDetail:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            result = await unit_of_work.case_law.update(source_id, request)
            if result is None:
                raise CaseLawSourceNotFoundError("Case-law source not found")
            await unit_of_work.commit()
            return result

    async def backfill_embeddings(self, *, batch_size: int = 64) -> int:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self._embedding_gateway is None:
            raise EmbeddingUnavailableError("embedding provider is not configured")
        embedding_model = self._embedding_gateway.model_name
        async with self._session_factory() as session:
            candidates = await LexoraUnitOfWork(
                session
            ).case_law.list_embedding_candidates(embedding_model)

        completed = 0
        for offset in range(0, len(candidates), batch_size):
            batch = candidates[offset : offset + batch_size]
            try:
                vectors = await self._embedding_gateway.embed_documents(
                    [content for _, content in batch]
                )
            except Exception as exc:
                raise EmbeddingUnavailableError(
                    f"failed to embed case-law batch at offset {offset}"
                ) from exc
            if len(vectors) != len(batch):
                raise EmbeddingUnavailableError(
                    "embedding provider returned an unexpected vector count"
                )
            async with self._session_factory() as session:
                unit_of_work = LexoraUnitOfWork(session)
                await unit_of_work.case_law.save_embeddings(
                    {
                        chunk_id: vector
                        for (chunk_id, _), vector in zip(batch, vectors, strict=True)
                    },
                    embedding_model,
                )
                await unit_of_work.commit()
            completed += len(batch)
        return completed
