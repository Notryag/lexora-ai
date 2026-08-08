from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from lexora_ai.application.errors import (
    DuplicateLegalSourceError,
    EmbeddingUnavailableError,
    LegalSourceNotFoundError,
)
from lexora_ai.application.ports import EmbeddingGateway
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import (
    LegalSourceCreate,
    LegalSourceDetail,
    LegalSourceSummary,
    LegalSourceUpdate,
)
from lexora_ai.legal_context import split_legal_source


class LegalSourceService:
    def __init__(
        self,
        session_factory: SessionFactory,
        embedding_gateway: EmbeddingGateway | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_gateway = embedding_gateway

    async def create(self, request: LegalSourceCreate) -> LegalSourceDetail:
        source_id = uuid4()
        chunks = split_legal_source(source_id, request.title, request.content)
        embeddings: list[tuple[float, ...]] | None = None
        embedding_model: str | None = None
        if self._embedding_gateway is not None:
            try:
                embeddings = await self._embedding_gateway.embed_documents(
                    [chunk.content for chunk in chunks]
                )
                embedding_model = self._embedding_gateway.model_name
            except Exception as exc:
                raise EmbeddingUnavailableError("failed to index legal source embeddings") from exc

        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            try:
                result = await unit_of_work.legal_sources.create(
                    request,
                    chunks,
                    source_id=source_id,
                    embeddings=embeddings,
                    embedding_model=embedding_model,
                )
                await unit_of_work.commit()
                return result
            except IntegrityError as exc:
                await unit_of_work.rollback()
                raise DuplicateLegalSourceError(
                    "this official source version has already been imported"
                ) from exc

    async def list(self) -> list[LegalSourceSummary]:
        async with self._session_factory() as session:
            return await LexoraUnitOfWork(session).legal_sources.list()

    async def get(self, source_id: UUID) -> LegalSourceDetail:
        async with self._session_factory() as session:
            result = await LexoraUnitOfWork(session).legal_sources.get(source_id)
            if result is None:
                raise LegalSourceNotFoundError("Legal source not found")
            return result

    async def delete(self, source_id: UUID) -> None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if not await unit_of_work.legal_sources.delete(source_id):
                raise LegalSourceNotFoundError("Legal source not found")
            await unit_of_work.commit()

    async def update(
        self,
        source_id: UUID,
        request: LegalSourceUpdate,
    ) -> LegalSourceDetail:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            result = await unit_of_work.legal_sources.update(source_id, request)
            if result is None:
                raise LegalSourceNotFoundError("Legal source not found")
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
            ).legal_sources.list_embedding_candidates(embedding_model)

        completed = 0
        for offset in range(0, len(candidates), batch_size):
            batch = candidates[offset : offset + batch_size]
            try:
                vectors = await self._embedding_gateway.embed_documents(
                    [content for _, content in batch]
                )
            except Exception as exc:
                raise EmbeddingUnavailableError(
                    f"failed to embed legal source batch at offset {offset}"
                ) from exc
            if len(vectors) != len(batch):
                raise EmbeddingUnavailableError(
                    "embedding provider returned an unexpected vector count"
                )
            async with self._session_factory() as session:
                unit_of_work = LexoraUnitOfWork(session)
                await unit_of_work.legal_sources.save_embeddings(
                    {
                        chunk_id: vector
                        for (chunk_id, _), vector in zip(batch, vectors, strict=True)
                    },
                    embedding_model,
                )
                await unit_of_work.commit()
            completed += len(batch)
        return completed
