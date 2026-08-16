from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated
from uuid import UUID

from agent_platform.core import ActiveThreadRunError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from north.runtime import END_SENTINEL, HEARTBEAT_SENTINEL, REPLAY_GAP_EVENT, StreamBridge
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
    CaseRunActivityHistory,
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
    get_run_task_registry,
    get_stream_bridge,
)
from .task_registry import BackgroundTaskRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def _sse_frame(event: str, data: object, *, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(
        "data: "
        + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    )
    return "\n".join(lines) + "\n\n"


def _pre_run_stream_error(error: BaseException) -> dict[str, str]:
    if isinstance(error, RunCancelledError):
        return {"code": "run_cancelled", "message": "分析已取消。"}
    if isinstance(error, ModelTemporarilyUnavailableError):
        return {"code": "provider_unavailable", "message": str(error)}
    if isinstance(error, (CaseNotFoundError, ModelNotConfiguredError, ActiveThreadRunError)):
        return {"code": "request_rejected", "message": str(error)}
    logger.error(
        "Case conversation stream failed before Run creation",
        extra={"error_type": type(error).__name__},
    )
    return {"code": "internal_error", "message": "分析失败，请稍后重试。"}


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
    http_request: Request,
    service: Annotated[
        PersistentLegalConversationService,
        Depends(get_persistent_conversation_service),
    ],
    stream_bridge: Annotated[StreamBridge, Depends(get_stream_bridge)],
    run_tasks: Annotated[BackgroundTaskRegistry, Depends(get_run_task_registry)],
    last_event_id: str | None = Header(
        default=None,
        alias="Last-Event-ID",
        pattern=r"^\d{1,20}-\d{1,20}$",
        max_length=41,
    ),
) -> StreamingResponse:
    async def event_stream():
        started: asyncio.Future[UUID] = asyncio.get_running_loop().create_future()

        async def publish_started(run_id: UUID) -> None:
            if not started.done():
                started.set_result(run_id)

        async def execute() -> None:
            try:
                await service.execute(
                    case_id,
                    request,
                    on_run_started=publish_started,
                )
            except BaseException as exc:
                if not started.done():
                    started.set_exception(exc)
                    return
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.exception("Case conversation stream failed", extra={"case_id": str(case_id)})

        run_tasks.create(execute())
        try:
            run_id = await started
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            yield _sse_frame("error", _pre_run_stream_error(exc))
            return

        async for entry in stream_bridge.subscribe(
            str(run_id),
            last_event_id=last_event_id,
        ):
            if await http_request.is_disconnected():
                return
            if entry == HEARTBEAT_SENTINEL:
                yield ": keep-alive\n\n"
                continue
            if entry == END_SENTINEL:
                yield _sse_frame("end", {})
                return
            if entry.event == REPLAY_GAP_EVENT:
                yield _sse_frame("gap", entry.data)
                continue
            yield _sse_frame(entry.event, entry.data, event_id=entry.id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
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


@router.get(
    "/cases/{case_id}/run/activities",
    response_model=CaseRunActivityHistory | None,
    tags=["case conversations"],
)
async def get_case_run_activities(
    case_id: UUID,
    service: Annotated[CaseRunService, Depends(get_case_run_service)],
) -> CaseRunActivityHistory | None:
    try:
        return await service.get_latest_activity_history(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/cases/{case_id}/runs/{run_id}/events/stream",
    tags=["case conversations"],
    response_class=StreamingResponse,
)
async def stream_existing_case_run(
    case_id: UUID,
    run_id: UUID,
    http_request: Request,
    service: Annotated[CaseRunService, Depends(get_case_run_service)],
    stream_bridge: Annotated[StreamBridge, Depends(get_stream_bridge)],
    last_event_id: str | None = Header(
        default=None,
        alias="Last-Event-ID",
        pattern=r"^\d{1,20}-\d{1,20}$",
        max_length=41,
    ),
) -> StreamingResponse:
    try:
        run = await service.get_for_case(case_id, run_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    async def event_stream():
        async for entry in stream_bridge.subscribe(
            str(run_id),
            last_event_id=last_event_id,
        ):
            if await http_request.is_disconnected():
                return
            if entry == HEARTBEAT_SENTINEL:
                yield ": keep-alive\n\n"
                continue
            if entry == END_SENTINEL:
                yield _sse_frame("end", {})
                return
            if entry.event == REPLAY_GAP_EVENT:
                yield _sse_frame("gap", entry.data)
                continue
            yield _sse_frame(entry.event, entry.data, event_id=entry.id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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
