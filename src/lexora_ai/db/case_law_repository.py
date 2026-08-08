from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lexora_ai.case_law_context import CaseLawChunkDraft
from lexora_ai.db.models import CaseLawChunkRow, CaseLawSourceRow
from lexora_ai.domain import (
    CaseLawChunk,
    CaseLawSourceCreate,
    CaseLawSourceDetail,
    CaseLawSourceSummary,
    CaseLawSourceUpdate,
    CaseLawStatus,
    LegalSourceReviewStatus,
)


def _summary(row: CaseLawSourceRow, *, chunk_count: int) -> CaseLawSourceSummary:
    return CaseLawSourceSummary(
        id=row.id,
        case_number=row.case_number,
        title=row.title,
        keywords=list(row.keywords or ()),
        issuing_authority=row.issuing_authority,
        status=row.status,
        published_on=row.published_on,
        source_name=row.source_name,
        source_url=row.source_url,
        review_status=row.review_status,
        content_sha256=row.content_sha256,
        verified_at=row.verified_at,
        chunk_count=chunk_count,
        created_at=row.created_at,
    )


class CaseLawRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        request: CaseLawSourceCreate,
        chunks: list[CaseLawChunkDraft],
        *,
        source_id: UUID,
    ) -> CaseLawSourceDetail:
        row = CaseLawSourceRow(
            id=source_id,
            case_number=request.case_number,
            title=request.title,
            keywords=request.keywords,
            issuing_authority=request.issuing_authority,
            status=request.status.value,
            published_on=request.published_on,
            source_name=request.source_name,
            source_url=request.source_url,
            content=request.content,
            content_sha256=sha256(request.content.encode()).hexdigest(),
            review_status=request.review_status.value,
            verified_at=request.verified_at,
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add_all(
            [
                CaseLawChunkRow(
                    source_id=source_id,
                    chunk_index=index,
                    reference=f"C{source_id.hex}:S{index}",
                    section_label=chunk.section_label,
                    content=chunk.content,
                )
                for index, chunk in enumerate(chunks, start=1)
            ]
        )
        await self.session.flush()
        await self.session.refresh(row)
        return CaseLawSourceDetail(
            **_summary(row, chunk_count=len(chunks)).model_dump(),
            content=row.content,
        )

    async def list(self) -> list[CaseLawSourceSummary]:
        rows = await self.session.execute(
            select(CaseLawSourceRow, func.count(CaseLawChunkRow.id))
            .outerjoin(CaseLawChunkRow, CaseLawChunkRow.source_id == CaseLawSourceRow.id)
            .group_by(CaseLawSourceRow.id)
            .order_by(CaseLawSourceRow.case_number.asc(), CaseLawSourceRow.created_at.desc())
        )
        return [_summary(row, chunk_count=count) for row, count in rows]

    async def get(self, source_id: UUID) -> CaseLawSourceDetail | None:
        result = (
            await self.session.execute(
                select(CaseLawSourceRow, func.count(CaseLawChunkRow.id))
                .outerjoin(CaseLawChunkRow, CaseLawChunkRow.source_id == CaseLawSourceRow.id)
                .where(CaseLawSourceRow.id == source_id)
                .group_by(CaseLawSourceRow.id)
            )
        ).one_or_none()
        if result is None:
            return None
        row, count = result
        return CaseLawSourceDetail(
            **_summary(row, chunk_count=count).model_dump(),
            content=row.content,
        )

    async def update(
        self,
        source_id: UUID,
        request: CaseLawSourceUpdate,
    ) -> CaseLawSourceDetail | None:
        row = await self.session.get(CaseLawSourceRow, source_id)
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
            select(func.count(CaseLawChunkRow.id)).where(CaseLawChunkRow.source_id == source_id)
        )
        return CaseLawSourceDetail(
            **_summary(row, chunk_count=count or 0).model_dump(),
            content=row.content,
        )

    async def list_approved_chunks(self) -> list[CaseLawChunk]:
        rows = await self.session.execute(
            select(CaseLawChunkRow, CaseLawSourceRow)
            .join(CaseLawSourceRow, CaseLawSourceRow.id == CaseLawChunkRow.source_id)
            .where(CaseLawSourceRow.status == CaseLawStatus.active.value)
            .where(CaseLawSourceRow.review_status == LegalSourceReviewStatus.approved.value)
            .order_by(CaseLawSourceRow.case_number.asc(), CaseLawChunkRow.chunk_index.asc())
        )
        return [
            CaseLawChunk(
                id=chunk.id,
                source_id=source.id,
                reference=chunk.reference,
                section_label=chunk.section_label,
                case_number=source.case_number,
                title=source.title,
                keywords=list(source.keywords or ()),
                issuing_authority=source.issuing_authority,
                source_url=source.source_url,
                published_on=source.published_on,
                content=chunk.content,
                embedding=(list(chunk.embedding) if chunk.embedding is not None else None),
                embedding_model=chunk.embedding_model,
            )
            for chunk, source in rows
        ]

    async def list_embedding_candidates(self, embedding_model: str) -> list[tuple[UUID, str]]:
        rows = await self.session.execute(
            select(CaseLawChunkRow.id, CaseLawChunkRow.content)
            .join(CaseLawSourceRow, CaseLawSourceRow.id == CaseLawChunkRow.source_id)
            .where(CaseLawSourceRow.status == CaseLawStatus.active.value)
            .where(CaseLawSourceRow.review_status == LegalSourceReviewStatus.approved.value)
            .where(
                or_(
                    CaseLawChunkRow.embedding.is_(None),
                    CaseLawChunkRow.embedding_model.is_(None),
                    CaseLawChunkRow.embedding_model != embedding_model,
                )
            )
            .order_by(CaseLawSourceRow.case_number.asc(), CaseLawChunkRow.chunk_index.asc())
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
                select(CaseLawChunkRow).where(CaseLawChunkRow.id.in_(embeddings))
            )
        ).all()
        if len(rows) != len(embeddings):
            raise ValueError("one or more case-law chunks no longer exist")
        for row in rows:
            row.embedding = list(embeddings[row.id])
            row.embedding_model = embedding_model
        await self.session.flush()
