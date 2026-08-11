from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from lexora_ai.db.models import LegalSourceChunkRow, LegalSourceRow
from lexora_ai.domain import (
    LegalKnowledgeChunk,
    LegalSourceCreate,
    LegalSourceDetail,
    LegalSourceReviewStatus,
    LegalSourceStatus,
    LegalSourceSummary,
    LegalSourceUpdate,
)
from lexora_ai.legal_context import LegalChunkDraft


def _summary(row: LegalSourceRow, *, chunk_count: int) -> LegalSourceSummary:
    return LegalSourceSummary(
        id=row.id,
        title=row.title,
        kind=row.kind,
        issuing_authority=row.issuing_authority,
        status=row.status,
        published_on=row.published_on,
        effective_on=row.effective_on,
        source_name=row.source_name,
        source_url=row.source_url,
        version_label=row.version_label,
        review_status=row.review_status,
        content_sha256=row.content_sha256,
        verified_at=row.verified_at,
        chunk_count=chunk_count,
        created_at=row.created_at,
    )


class LegalSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        request: LegalSourceCreate,
        chunks: list[LegalChunkDraft],
        *,
        source_id: UUID,
        embeddings: list[tuple[float, ...]] | None,
        embedding_model: str | None,
    ) -> LegalSourceDetail:
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError("legal source embeddings must match chunks")
        row = LegalSourceRow(
            id=source_id,
            title=request.title,
            kind=request.kind.value,
            issuing_authority=request.issuing_authority,
            status=request.status.value,
            published_on=request.published_on,
            effective_on=request.effective_on,
            source_name=request.source_name,
            source_url=request.source_url,
            version_label=request.version_label,
            content=request.content,
            content_sha256=sha256(request.content.encode()).hexdigest(),
            review_status=request.review_status.value,
            verified_at=request.verified_at,
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add_all(
            [
                LegalSourceChunkRow(
                    source_id=source_id,
                    chunk_index=index,
                    reference=f"L{source_id.hex}:C{index}",
                    article_label=chunk.article_label,
                    heading_path=list(chunk.heading_path),
                    content=chunk.content,
                    embedding=(list(embeddings[index - 1]) if embeddings is not None else None),
                    embedding_model=embedding_model,
                )
                for index, chunk in enumerate(chunks, start=1)
            ]
        )
        await self.session.flush()
        await self.session.refresh(row)
        return LegalSourceDetail(
            **_summary(row, chunk_count=len(chunks)).model_dump(), content=row.content
        )

    async def list(self) -> list[LegalSourceSummary]:
        rows = await self.session.execute(
            select(LegalSourceRow, func.count(LegalSourceChunkRow.id))
            .outerjoin(LegalSourceChunkRow, LegalSourceChunkRow.source_id == LegalSourceRow.id)
            .group_by(LegalSourceRow.id)
            .order_by(LegalSourceRow.created_at.desc(), LegalSourceRow.id.desc())
        )
        return [_summary(row, chunk_count=count) for row, count in rows]

    async def get(self, source_id: UUID) -> LegalSourceDetail | None:
        result = (
            await self.session.execute(
                select(LegalSourceRow, func.count(LegalSourceChunkRow.id))
                .outerjoin(LegalSourceChunkRow, LegalSourceChunkRow.source_id == LegalSourceRow.id)
                .where(LegalSourceRow.id == source_id)
                .group_by(LegalSourceRow.id)
            )
        ).one_or_none()
        if result is None:
            return None
        row, count = result
        return LegalSourceDetail(
            **_summary(row, chunk_count=count).model_dump(), content=row.content
        )

    async def delete(self, source_id: UUID) -> bool:
        result = await self.session.execute(
            delete(LegalSourceRow).where(LegalSourceRow.id == source_id)
        )
        return bool(result.rowcount)

    async def update(
        self,
        source_id: UUID,
        request: LegalSourceUpdate,
    ) -> LegalSourceDetail | None:
        row = await self.session.get(LegalSourceRow, source_id)
        if row is None:
            return None
        if request.status is not None:
            row.status = request.status.value
        if request.review_status is not None:
            row.review_status = request.review_status.value
            row.verified_at = request.verified_at
        await self.session.flush()
        await self.session.refresh(row)
        count = await self.session.scalar(
            select(func.count(LegalSourceChunkRow.id)).where(
                LegalSourceChunkRow.source_id == source_id
            )
        )
        return LegalSourceDetail(
            **_summary(row, chunk_count=count or 0).model_dump(),
            content=row.content,
        )

    async def list_effective_chunks(
        self,
        *,
        include_embeddings: bool = True,
        chunk_ids: Sequence[UUID] | None = None,
        limit: int | None = None,
    ) -> list[LegalKnowledgeChunk]:
        if (chunk_ids is not None and not chunk_ids) or (limit is not None and limit <= 0):
            return []
        query = (
            select(LegalSourceChunkRow, LegalSourceRow)
            .join(LegalSourceRow, LegalSourceRow.id == LegalSourceChunkRow.source_id)
            .where(LegalSourceRow.status == LegalSourceStatus.effective.value)
            .where(LegalSourceRow.review_status == LegalSourceReviewStatus.approved.value)
            .order_by(LegalSourceRow.title.asc(), LegalSourceChunkRow.chunk_index.asc())
        )
        if chunk_ids is not None:
            query = query.where(LegalSourceChunkRow.id.in_(chunk_ids))
        query = query.options(defer(LegalSourceRow.content))
        if not include_embeddings:
            query = query.options(defer(LegalSourceChunkRow.embedding))
        if limit is not None:
            query = query.limit(limit)
        rows = await self.session.execute(query)
        return [
            LegalKnowledgeChunk(
                id=chunk.id,
                source_id=source.id,
                reference=chunk.reference,
                article_label=chunk.article_label,
                heading_path=tuple(chunk.heading_path or ()),
                title=source.title,
                issuing_authority=source.issuing_authority,
                source_url=source.source_url,
                status=source.status,
                content=chunk.content,
                embedding=(
                    list(chunk.embedding)
                    if include_embeddings and chunk.embedding is not None
                    else None
                ),
                embedding_model=chunk.embedding_model,
            )
            for chunk, source in rows
        ]

    async def list_effective_vector_candidate_ids(
        self,
        query_embedding: tuple[float, ...],
        embedding_model: str,
        *,
        limit: int,
    ) -> list[UUID]:
        if not query_embedding or limit <= 0:
            return []
        distance = LegalSourceChunkRow.embedding.cosine_distance(list(query_embedding))
        rows = await self.session.scalars(
            select(LegalSourceChunkRow.id)
            .join(LegalSourceRow, LegalSourceRow.id == LegalSourceChunkRow.source_id)
            .where(LegalSourceRow.status == LegalSourceStatus.effective.value)
            .where(LegalSourceRow.review_status == LegalSourceReviewStatus.approved.value)
            .where(LegalSourceChunkRow.embedding.is_not(None))
            .where(LegalSourceChunkRow.embedding_model == embedding_model)
            .order_by(distance, LegalSourceChunkRow.id)
            .limit(limit)
        )
        return list(rows)

    async def list_embedding_candidates(
        self,
        embedding_model: str,
    ) -> list[tuple[UUID, str]]:
        rows = await self.session.execute(
            select(LegalSourceChunkRow.id, LegalSourceChunkRow.content)
            .join(LegalSourceRow, LegalSourceRow.id == LegalSourceChunkRow.source_id)
            .where(LegalSourceRow.status == LegalSourceStatus.effective.value)
            .where(LegalSourceRow.review_status == LegalSourceReviewStatus.approved.value)
            .where(
                or_(
                    LegalSourceChunkRow.embedding.is_(None),
                    LegalSourceChunkRow.embedding_model.is_(None),
                    LegalSourceChunkRow.embedding_model != embedding_model,
                )
            )
            .order_by(LegalSourceRow.title.asc(), LegalSourceChunkRow.chunk_index.asc())
        )
        return [(chunk_id, content) for chunk_id, content in rows]

    async def save_embeddings(
        self,
        embeddings: dict[UUID, tuple[float, ...]],
        embedding_model: str,
    ) -> None:
        if not embeddings:
            return
        rows = (
            await self.session.scalars(
                select(LegalSourceChunkRow).where(
                    LegalSourceChunkRow.id.in_(embeddings)
                )
            )
        ).all()
        if len(rows) != len(embeddings):
            raise ValueError("one or more legal source chunks no longer exist")
        for row in rows:
            row.embedding = list(embeddings[row.id])
            row.embedding_model = embedding_model
        await self.session.flush()
