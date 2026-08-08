from __future__ import annotations

from uuid import UUID

from agent_platform.core import UserContext
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lexora_ai.db.models import CaseMaterialChunkRow, CaseMaterialRow, LegalCaseRow
from lexora_ai.domain import (
    CaseMaterial,
    CaseProfile,
    CaseProfileUpdate,
    LegalCase,
    LegalCaseCreate,
    LegalCaseUpdate,
    MaterialKind,
    StoredCaseMaterial,
    StoredMaterialChunk,
)


def legal_case_from_row(row: LegalCaseRow, *, material_count: int) -> LegalCase:
    return LegalCase(
        id=row.id,
        title=row.title,
        background=row.background,
        profile=CaseProfile.model_validate(row.profile or {}),
        material_count=material_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def material_from_row(row: CaseMaterialRow) -> StoredCaseMaterial:
    return StoredCaseMaterial(
        material_id=row.id,
        case_id=row.case_id,
        reference_index=row.reference_index,
        title=row.title,
        kind=MaterialKind(row.kind),
        content=row.content,
        source_note=row.source_note,
        original_filename=row.original_filename,
        media_type=row.media_type,
        created_at=row.created_at,
    )


class CaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, context: UserContext, request: LegalCaseCreate) -> LegalCase:
        row = LegalCaseRow(
            owner_id=context.user_id,
            title=request.title,
            background=request.background,
            profile={},
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return legal_case_from_row(row, material_count=0)

    async def get(self, context: UserContext, case_id: UUID) -> LegalCase | None:
        statement = (
            select(LegalCaseRow, func.count(CaseMaterialRow.id))
            .outerjoin(CaseMaterialRow, CaseMaterialRow.case_id == LegalCaseRow.id)
            .where(LegalCaseRow.id == case_id, LegalCaseRow.owner_id == context.user_id)
            .group_by(LegalCaseRow.id)
        )
        result = (await self.session.execute(statement)).one_or_none()
        return legal_case_from_row(result[0], material_count=result[1]) if result else None

    async def list(self, context: UserContext) -> list[LegalCase]:
        statement = (
            select(LegalCaseRow, func.count(CaseMaterialRow.id))
            .outerjoin(CaseMaterialRow, CaseMaterialRow.case_id == LegalCaseRow.id)
            .where(LegalCaseRow.owner_id == context.user_id)
            .group_by(LegalCaseRow.id)
            .order_by(LegalCaseRow.updated_at.desc(), LegalCaseRow.id.desc())
        )
        rows = await self.session.execute(statement)
        return [legal_case_from_row(row, material_count=count) for row, count in rows]

    async def update(
        self,
        context: UserContext,
        case_id: UUID,
        request: LegalCaseUpdate,
    ) -> LegalCase | None:
        row = await self.session.scalar(
            update(LegalCaseRow)
            .where(LegalCaseRow.id == case_id, LegalCaseRow.owner_id == context.user_id)
            .values(title=request.title, updated_at=func.now())
            .returning(LegalCaseRow)
        )
        if row is None:
            return None
        count = await self.session.scalar(
            select(func.count(CaseMaterialRow.id)).where(CaseMaterialRow.case_id == case_id)
        )
        return legal_case_from_row(row, material_count=count or 0)

    async def update_profile(
        self,
        context: UserContext,
        case_id: UUID,
        request: CaseProfileUpdate,
    ) -> LegalCase | None:
        row = await self.session.scalar(
            update(LegalCaseRow)
            .where(LegalCaseRow.id == case_id, LegalCaseRow.owner_id == context.user_id)
            .values(profile=request.model_dump(mode="json"), updated_at=func.now())
            .returning(LegalCaseRow)
        )
        if row is None:
            return None
        count = await self.session.scalar(
            select(func.count(CaseMaterialRow.id)).where(CaseMaterialRow.case_id == case_id)
        )
        return legal_case_from_row(row, material_count=count or 0)

    async def delete(self, context: UserContext, case_id: UUID) -> bool:
        result = await self.session.execute(
            delete(LegalCaseRow).where(
                LegalCaseRow.id == case_id,
                LegalCaseRow.owner_id == context.user_id,
            )
        )
        return bool(result.rowcount)

    async def lock(self, context: UserContext, case_id: UUID) -> bool:
        row_id = await self.session.scalar(
            select(LegalCaseRow.id)
            .where(LegalCaseRow.id == case_id, LegalCaseRow.owner_id == context.user_id)
            .with_for_update()
        )
        return row_id is not None

    async def add_material(
        self,
        context: UserContext,
        case_id: UUID,
        material: CaseMaterial,
        *,
        chunk_contents: list[str],
        chunk_embeddings: list[tuple[float, ...]] | None = None,
        embedding_model: str | None = None,
        original_filename: str | None = None,
        media_type: str | None = None,
    ) -> StoredCaseMaterial:
        if chunk_embeddings is not None and len(chunk_embeddings) != len(chunk_contents):
            raise ValueError("chunk embeddings must match chunk contents")
        reference_index = (
            await self.session.scalar(
                select(func.coalesce(func.max(CaseMaterialRow.reference_index), 0)).where(
                    CaseMaterialRow.case_id == case_id,
                    CaseMaterialRow.owner_id == context.user_id,
                )
            )
        ) + 1
        row = CaseMaterialRow(
            id=material.material_id,
            case_id=case_id,
            owner_id=context.user_id,
            reference_index=reference_index,
            title=material.title,
            kind=material.kind.value,
            content=material.content,
            source_note=material.source_note,
            original_filename=original_filename,
            media_type=media_type,
        )
        self.session.add(row)
        await self.session.flush()
        self.session.add_all(
            [
                CaseMaterialChunkRow(
                    case_id=case_id,
                    material_id=material.material_id,
                    owner_id=context.user_id,
                    chunk_index=index,
                    reference=f"M{reference_index}:C{index}",
                    content=chunk_content,
                    embedding=(
                        list(chunk_embeddings[index - 1])
                        if chunk_embeddings is not None
                        else None
                    ),
                    embedding_model=embedding_model,
                )
                for index, chunk_content in enumerate(chunk_contents, start=1)
            ]
        )
        await self.session.execute(
            update(LegalCaseRow)
            .where(LegalCaseRow.id == case_id, LegalCaseRow.owner_id == context.user_id)
            .values(updated_at=func.now())
        )
        await self.session.flush()
        await self.session.refresh(row)
        return material_from_row(row)

    async def list_material_chunks(
        self,
        context: UserContext,
        case_id: UUID,
    ) -> list[StoredMaterialChunk]:
        rows = await self.session.execute(
            select(CaseMaterialChunkRow, CaseMaterialRow)
            .join(CaseMaterialRow, CaseMaterialRow.id == CaseMaterialChunkRow.material_id)
            .where(
                CaseMaterialChunkRow.case_id == case_id,
                CaseMaterialChunkRow.owner_id == context.user_id,
            )
            .order_by(
                CaseMaterialRow.reference_index.asc(),
                CaseMaterialChunkRow.chunk_index.asc(),
            )
        )
        return [
            StoredMaterialChunk(
                id=chunk.id,
                case_id=chunk.case_id,
                material_id=chunk.material_id,
                reference=chunk.reference,
                title=material.title,
                kind=MaterialKind(material.kind),
                source_note=material.source_note,
                content=chunk.content,
                embedding=(list(chunk.embedding) if chunk.embedding is not None else None),
                embedding_model=chunk.embedding_model,
            )
            for chunk, material in rows
        ]

    async def list_materials(
        self,
        context: UserContext,
        case_id: UUID,
    ) -> list[StoredCaseMaterial]:
        rows = await self.session.scalars(
            select(CaseMaterialRow)
            .where(
                CaseMaterialRow.case_id == case_id,
                CaseMaterialRow.owner_id == context.user_id,
            )
            .order_by(CaseMaterialRow.created_at.asc(), CaseMaterialRow.id.asc())
        )
        return [material_from_row(row) for row in rows]

    async def delete_material(
        self,
        context: UserContext,
        case_id: UUID,
        material_id: UUID,
    ) -> bool:
        result = await self.session.execute(
            delete(CaseMaterialRow).where(
                CaseMaterialRow.id == material_id,
                CaseMaterialRow.case_id == case_id,
                CaseMaterialRow.owner_id == context.user_id,
            )
        )
        return bool(result.rowcount)
