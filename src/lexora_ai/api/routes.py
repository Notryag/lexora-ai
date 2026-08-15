from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Annotated
from uuid import UUID

from agent_platform.core import ActiveThreadRunError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from lexora_ai.application import (
    ActiveCaseRunNotFoundError,
    AnalyzeCaseService,
    CaseNotFoundError,
    CaseRunService,
    CaseWorkspaceService,
    DuplicateLegalSourceError,
    EmbeddingUnavailableError,
    LegalConversationService,
    LegalSourceNotFoundError,
    LegalSourceService,
    MaterialLimitError,
    MaterialNotFoundError,
    MaterialParseError,
    PersistentLegalConversationService,
    RunCancelledError,
)
from lexora_ai.domain import (
    CaseAnalysisRequest,
    CaseAnalysisResult,
    CaseConversationMessage,
    CaseConversationTurnRequest,
    CaseConversationTurnResult,
    CaseMaterial,
    CaseProfileUpdate,
    CaseRun,
    ConversationTurnRequest,
    ConversationTurnResult,
    LegalCase,
    LegalCaseCreate,
    LegalCaseUpdate,
    LegalSourceCreate,
    LegalSourceDetail,
    LegalSourceSummary,
    LegalSourceUpdate,
    MaterialKind,
    StoredCaseMaterial,
)
from lexora_ai.infrastructure import (
    ModelNotConfiguredError,
    ModelTemporarilyUnavailableError,
)

from .dependencies import (
    get_analyze_case_service,
    get_case_run_service,
    get_case_workspace_service,
    get_legal_conversation_service,
    get_legal_source_service,
    get_persistent_conversation_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="lexora-ai", version="0.1.0")


@router.post(
    "/legal-sources",
    response_model=LegalSourceDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["legal knowledge"],
    include_in_schema=False,
)
async def create_legal_source(
    request: LegalSourceCreate,
    service: Annotated[LegalSourceService, Depends(get_legal_source_service)],
) -> LegalSourceDetail:
    try:
        return await service.create(request)
    except DuplicateLegalSourceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EmbeddingUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/legal-sources",
    response_model=list[LegalSourceSummary],
    tags=["legal knowledge"],
)
async def list_legal_sources(
    service: Annotated[LegalSourceService, Depends(get_legal_source_service)],
) -> list[LegalSourceSummary]:
    return await service.list()


@router.get(
    "/legal-sources/{source_id}",
    response_model=LegalSourceDetail,
    tags=["legal knowledge"],
)
async def get_legal_source(
    source_id: UUID,
    service: Annotated[LegalSourceService, Depends(get_legal_source_service)],
) -> LegalSourceDetail:
    try:
        return await service.get(source_id)
    except LegalSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/legal-sources/{source_id}",
    response_model=LegalSourceDetail,
    tags=["legal knowledge"],
    include_in_schema=False,
)
async def update_legal_source(
    source_id: UUID,
    request: LegalSourceUpdate,
    service: Annotated[LegalSourceService, Depends(get_legal_source_service)],
) -> LegalSourceDetail:
    try:
        return await service.update(source_id, request)
    except LegalSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/legal-sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["legal knowledge"],
    include_in_schema=False,
)
async def delete_legal_source(
    source_id: UUID,
    service: Annotated[LegalSourceService, Depends(get_legal_source_service)],
) -> None:
    try:
        await service.delete(source_id)
    except LegalSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/analyses",
    response_model=CaseAnalysisResult,
    status_code=status.HTTP_201_CREATED,
    tags=["case analysis"],
)
async def create_analysis(
    request: CaseAnalysisRequest,
    service: Annotated[AnalyzeCaseService, Depends(get_analyze_case_service)],
) -> CaseAnalysisResult:
    try:
        return await service.execute(request)
    except ModelNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ModelTemporarilyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/conversations/messages",
    response_model=ConversationTurnResult,
    tags=["legal conversation"],
)
async def create_conversation_turn(
    request: ConversationTurnRequest,
    service: Annotated[
        LegalConversationService,
        Depends(get_legal_conversation_service),
    ],
) -> ConversationTurnResult:
    try:
        return await service.execute(request)
    except ModelNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ModelTemporarilyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@router.post(
    "/cases", response_model=LegalCase, status_code=status.HTTP_201_CREATED, tags=["cases"]
)
async def create_case(
    request: LegalCaseCreate,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> LegalCase:
    return await service.create_case(request)


@router.get("/cases", response_model=list[LegalCase], tags=["cases"])
async def list_cases(
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> list[LegalCase]:
    return await service.list_cases()


@router.get("/cases/{case_id}", response_model=LegalCase, tags=["cases"])
async def get_case(
    case_id: UUID,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> LegalCase:
    try:
        return await service.get_case(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/cases/{case_id}", response_model=LegalCase, tags=["cases"])
async def update_case(
    case_id: UUID,
    request: LegalCaseUpdate,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> LegalCase:
    try:
        return await service.update_case(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/cases/{case_id}/profile", response_model=LegalCase, tags=["cases"])
async def update_case_profile(
    case_id: UUID,
    request: CaseProfileUpdate,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> LegalCase:
    try:
        return await service.update_profile(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["cases"])
async def delete_case(
    case_id: UUID,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> None:
    try:
        await service.delete_case(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/cases/{case_id}/materials",
    response_model=StoredCaseMaterial,
    status_code=status.HTTP_201_CREATED,
    tags=["case materials"],
)
async def add_case_material(
    case_id: UUID,
    material: CaseMaterial,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> StoredCaseMaterial:
    try:
        return await service.add_material(case_id, material)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MaterialLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except EmbeddingUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/cases/{case_id}/materials/upload",
    response_model=StoredCaseMaterial,
    status_code=status.HTTP_201_CREATED,
    tags=["case materials"],
)
async def upload_case_material(
    case_id: UUID,
    file: Annotated[UploadFile, File()],
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
    kind: Annotated[MaterialKind, Form()] = MaterialKind.other,
    source_note: Annotated[str | None, Form(max_length=500)] = None,
) -> StoredCaseMaterial:
    try:
        return await service.upload_material(
            case_id,
            filename=file.filename or "material.txt",
            media_type=file.content_type,
            content=await file.read(10 * 1024 * 1024 + 1),
            kind=kind,
            source_note=source_note,
        )
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MaterialParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except MaterialLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except EmbeddingUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/cases/{case_id}/materials",
    response_model=list[StoredCaseMaterial],
    tags=["case materials"],
)
async def list_case_materials(
    case_id: UUID,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> list[StoredCaseMaterial]:
    try:
        return await service.list_materials(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/cases/{case_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["case materials"],
)
async def delete_case_material(
    case_id: UUID,
    material_id: UUID,
    service: Annotated[CaseWorkspaceService, Depends(get_case_workspace_service)],
) -> None:
    try:
        await service.delete_material(case_id, material_id)
    except MaterialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/cases/{case_id}/messages",
    response_model=CaseConversationTurnResult,
    tags=["case conversations"],
)
async def create_case_conversation_turn(
    case_id: UUID,
    request: CaseConversationTurnRequest,
    service: Annotated[
        PersistentLegalConversationService,
        Depends(get_persistent_conversation_service),
    ],
) -> CaseConversationTurnResult:
    try:
        return await service.execute(case_id, request)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ModelNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ModelTemporarilyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ActiveThreadRunError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RunCancelledError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/cases/{case_id}/messages/stream",
    tags=["case conversations"],
    response_class=StreamingResponse,
)
async def stream_case_conversation_turn(
    case_id: UUID,
    request: CaseConversationTurnRequest,
    service: Annotated[
        PersistentLegalConversationService,
        Depends(get_persistent_conversation_service),
    ],
) -> StreamingResponse:
    async def event_stream():
        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        def publish_delta(delta: str) -> None:
            queue.put_nowait(("delta", delta))

        async def execute() -> None:
            try:
                result = await service.execute(
                    case_id,
                    request,
                    on_text_delta=publish_delta,
                )
                await queue.put(("complete", result))
            except RunCancelledError:
                await queue.put(
                    ("error", {"code": "run_cancelled", "message": "分析已取消。"})
                )
            except ModelTemporarilyUnavailableError as exc:
                await queue.put(
                    (
                        "error",
                        {"code": "provider_unavailable", "message": str(exc)},
                    )
                )
            except (CaseNotFoundError, ModelNotConfiguredError, ActiveThreadRunError) as exc:
                await queue.put(
                    ("error", {"code": "request_rejected", "message": str(exc)})
                )
            except Exception:
                logger.exception("Case conversation stream failed", extra={"case_id": str(case_id)})
                await queue.put(
                    (
                        "error",
                        {"code": "internal_error", "message": "分析失败，请稍后重试。"},
                    )
                )
            finally:
                await queue.put(("end", None))

        task = asyncio.create_task(execute())
        try:
            while True:
                event_type, payload = await queue.get()
                if event_type == "end":
                    break
                if event_type == "complete":
                    data = {
                        "type": "complete",
                        "result": payload.model_dump(mode="json"),
                    }
                elif event_type == "delta":
                    data = {"type": "delta", "delta": payload}
                else:
                    data = {"type": "error", **payload}
                yield json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/cases/{case_id}/run",
    response_model=CaseRun | None,
    tags=["case conversations"],
)
async def get_case_run(
    case_id: UUID,
    service: Annotated[CaseRunService, Depends(get_case_run_service)],
) -> CaseRun | None:
    try:
        return await service.get_latest(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/cases/{case_id}/run/cancel",
    response_model=CaseRun,
    tags=["case conversations"],
)
async def cancel_case_run(
    case_id: UUID,
    service: Annotated[CaseRunService, Depends(get_case_run_service)],
) -> CaseRun:
    try:
        return await service.cancel_active(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ActiveCaseRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/cases/{case_id}/messages",
    response_model=list[CaseConversationMessage],
    tags=["case conversations"],
)
async def list_case_conversation_messages(
    case_id: UUID,
    service: Annotated[
        PersistentLegalConversationService,
        Depends(get_persistent_conversation_service),
    ],
) -> list[CaseConversationMessage]:
    try:
        return await service.list_messages(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
