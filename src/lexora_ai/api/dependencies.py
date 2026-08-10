from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from agent_platform.core import UserContext
from fastapi import Depends, Request
from north import CheckpointerConfig, make_checkpointer

from lexora_ai.application import (
    AnalyzeCaseService,
    CaseLawSourceService,
    CaseRunService,
    CaseWorkspaceService,
    LegalConversationService,
    LegalSourceService,
    PersistentLegalConversationService,
)
from lexora_ai.config import get_settings
from lexora_ai.db import build_engine, build_session_factory
from lexora_ai.infrastructure import (
    DatabaseCaseLawKnowledgePort,
    DatabaseLegalKnowledgePort,
    NorthCaseAnalysisGateway,
    OpenAIEmbeddingGateway,
)
from lexora_ai.infrastructure.material_parser import parse_material_file


async def get_north_gateway(request: Request) -> NorthCaseAnalysisGateway:
    existing = getattr(request.app.state, "north_gateway", None)
    if existing is not None:
        return existing
    async with request.app.state.north_gateway_lock:
        existing = getattr(request.app.state, "north_gateway", None)
        if existing is not None:
            return existing
        settings = get_settings()
        manager = make_checkpointer(
            CheckpointerConfig(
                backend=settings.agent_checkpointer_backend,
                connection_string=settings.checkpointer_connection_string,
            )
        )
        checkpointer = await manager.__aenter__()
        gateway = NorthCaseAnalysisGateway(settings, checkpointer=checkpointer)
        request.app.state.checkpointer_manager = manager
        request.app.state.north_gateway = gateway
        return gateway


@lru_cache(maxsize=1)
def get_embedding_gateway() -> OpenAIEmbeddingGateway | None:
    settings = get_settings()
    if settings.embedding_api_key is None and settings.openai_api_key is None:
        return None
    return OpenAIEmbeddingGateway(settings)


@lru_cache(maxsize=1)
def get_legal_knowledge_port() -> DatabaseLegalKnowledgePort:
    return DatabaseLegalKnowledgePort(get_session_factory())


@lru_cache(maxsize=1)
def get_case_law_knowledge_port() -> DatabaseCaseLawKnowledgePort:
    return DatabaseCaseLawKnowledgePort(get_session_factory())


@lru_cache(maxsize=1)
def get_session_factory():
    return build_session_factory(build_engine(get_settings().database_url))


@lru_cache(maxsize=1)
def get_personal_user_context() -> UserContext:
    settings = get_settings()
    return UserContext(
        user_id=settings.personal_user_id,
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )


def get_analyze_case_service(
    gateway: Annotated[NorthCaseAnalysisGateway, Depends(get_north_gateway)],
) -> AnalyzeCaseService:
    return AnalyzeCaseService(gateway)


def get_legal_conversation_service(
    gateway: Annotated[NorthCaseAnalysisGateway, Depends(get_north_gateway)],
) -> LegalConversationService:
    return LegalConversationService(gateway)


@lru_cache(maxsize=1)
def get_case_workspace_service() -> CaseWorkspaceService:
    return CaseWorkspaceService(
        get_session_factory(),
        get_personal_user_context(),
        parse_material_file,
        get_embedding_gateway(),
    )


@lru_cache(maxsize=1)
def get_legal_source_service() -> LegalSourceService:
    return LegalSourceService(get_session_factory(), get_embedding_gateway())


@lru_cache(maxsize=1)
def get_case_law_source_service() -> CaseLawSourceService:
    return CaseLawSourceService(get_session_factory(), get_embedding_gateway())


@lru_cache(maxsize=1)
def get_case_run_service() -> CaseRunService:
    return CaseRunService(get_session_factory(), get_personal_user_context())


def get_persistent_conversation_service(
    gateway: Annotated[NorthCaseAnalysisGateway, Depends(get_north_gateway)],
) -> PersistentLegalConversationService:
    return PersistentLegalConversationService(
        get_session_factory(),
        get_personal_user_context(),
        gateway,
        get_embedding_gateway(),
        get_legal_knowledge_port(),
        get_case_law_knowledge_port(),
    )
