from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from agent_platform.core import UserContext

from lexora_ai.application.errors import (
    CaseNotFoundError,
    EmbeddingUnavailableError,
    MaterialLimitError,
    MaterialNotFoundError,
)
from lexora_ai.application.ports import EmbeddingGateway
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import (
    CaseMaterial,
    CaseProfileUpdate,
    LegalCase,
    LegalCaseCreate,
    LegalCaseUpdate,
    MaterialKind,
    StoredCaseMaterial,
)
from lexora_ai.domain.cases import MAX_MATERIALS, MAX_TOTAL_MATERIAL_CHARS
from lexora_ai.material_context import build_material_context

MaterialParser = Callable[[str, bytes], str]


class CaseWorkspaceService:
    def __init__(
        self,
        session_factory: SessionFactory,
        context: UserContext,
        material_parser: MaterialParser,
        embedding_gateway: EmbeddingGateway | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._material_parser = material_parser
        self._embedding_gateway = embedding_gateway

    async def create_case(self, request: LegalCaseCreate) -> LegalCase:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            result = await unit_of_work.cases.create(self._context, request)
            await unit_of_work.threads.get_or_create_for_case(
                self._context,
                case_id=result.id,
                title=result.title,
            )
            await unit_of_work.commit()
            return result

    async def list_cases(self) -> list[LegalCase]:
        async with self._session_factory() as session:
            return await LexoraUnitOfWork(session).cases.list(self._context)

    async def get_case(self, case_id: UUID) -> LegalCase:
        async with self._session_factory() as session:
            result = await LexoraUnitOfWork(session).cases.get(self._context, case_id)
            if result is None:
                raise CaseNotFoundError("Case not found")
            return result

    async def update_case(self, case_id: UUID, request: LegalCaseUpdate) -> LegalCase:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            result = await unit_of_work.cases.update(self._context, case_id, request)
            if result is None:
                raise CaseNotFoundError("Case not found")
            thread = await unit_of_work.threads.get_for_case(self._context, case_id)
            if thread is not None:
                await unit_of_work.threads.update_title(
                    self._context,
                    thread.id,
                    result.title,
                )
            await unit_of_work.commit()
            return result

    async def delete_case(self, case_id: UUID) -> None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if not await unit_of_work.cases.delete(self._context, case_id):
                raise CaseNotFoundError("Case not found")
            await unit_of_work.commit()

    async def update_profile(self, case_id: UUID, request: CaseProfileUpdate) -> LegalCase:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            result = await unit_of_work.cases.update_profile(self._context, case_id, request)
            if result is None:
                raise CaseNotFoundError("Case not found")
            await unit_of_work.commit()
            return result

    async def add_material(self, case_id: UUID, material: CaseMaterial) -> StoredCaseMaterial:
        return await self._store_material(case_id, material)

    async def upload_material(
        self,
        case_id: UUID,
        *,
        filename: str,
        media_type: str | None,
        content: bytes,
        kind: MaterialKind,
        source_note: str | None,
    ) -> StoredCaseMaterial:
        extracted = self._material_parser(filename, content)
        material = CaseMaterial(
            title=Path(filename).stem[:200] or "未命名材料",
            kind=kind,
            content=extracted,
            source_note=source_note,
        )
        return await self._store_material(
            case_id,
            material,
            original_filename=filename,
            media_type=media_type,
        )

    async def _store_material(
        self,
        case_id: UUID,
        material: CaseMaterial,
        *,
        original_filename: str | None = None,
        media_type: str | None = None,
    ) -> StoredCaseMaterial:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            case = await unit_of_work.cases.get(self._context, case_id)
            if case is None:
                raise CaseNotFoundError("Case not found")
            existing_materials = await unit_of_work.cases.list_materials(
                self._context,
                case_id,
            )
            self._validate_capacity(existing_materials, material)

        chunks = build_material_context([material])
        chunk_embeddings: list[tuple[float, ...]] | None = None
        embedding_model: str | None = None
        if self._embedding_gateway is not None:
            try:
                chunk_embeddings = await self._embedding_gateway.embed_documents(
                    [chunk.content for chunk in chunks]
                )
                embedding_model = self._embedding_gateway.model_name
            except Exception as exc:
                raise EmbeddingUnavailableError("failed to index material embeddings") from exc

        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            case = await unit_of_work.cases.get(self._context, case_id)
            if case is None:
                raise CaseNotFoundError("Case not found")
            await unit_of_work.cases.lock(self._context, case_id)
            existing_materials = await unit_of_work.cases.list_materials(
                self._context,
                case_id,
            )
            self._validate_capacity(existing_materials, material)
            result = await unit_of_work.cases.add_material(
                self._context,
                case_id,
                material,
                chunk_contents=[chunk.content for chunk in chunks],
                chunk_embeddings=chunk_embeddings,
                embedding_model=embedding_model,
                original_filename=original_filename,
                media_type=media_type,
            )
            await unit_of_work.commit()
            return result

    @staticmethod
    def _validate_capacity(
        existing_materials: list[StoredCaseMaterial],
        material: CaseMaterial,
    ) -> None:
        if len(existing_materials) >= MAX_MATERIALS:
            raise MaterialLimitError(f"a case may contain at most {MAX_MATERIALS} materials")
        total_chars = sum(len(item.content) for item in existing_materials) + len(material.content)
        if total_chars > MAX_TOTAL_MATERIAL_CHARS:
            raise MaterialLimitError(
                "total material content must contain at most "
                f"{MAX_TOTAL_MATERIAL_CHARS} characters"
            )

    async def list_materials(self, case_id: UUID) -> list[StoredCaseMaterial]:
        await self.get_case(case_id)
        async with self._session_factory() as session:
            return await LexoraUnitOfWork(session).cases.list_materials(
                self._context,
                case_id,
            )

    async def delete_material(self, case_id: UUID, material_id: UUID) -> None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if not await unit_of_work.cases.delete_material(
                self._context,
                case_id,
                material_id,
            ):
                raise MaterialNotFoundError("Material not found")
            await unit_of_work.commit()
