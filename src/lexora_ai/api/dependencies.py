from __future__ import annotations

from functools import lru_cache

from agent_platform.core import UserContext

from lexora_ai.application import (
    AnalyzeCaseService,
    CaseLawSourceService,
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


@lru_cache(maxsize=1)
def get_north_gateway() -> NorthCaseAnalysisGateway:
    return NorthCaseAnalysisGateway(get_settings())


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


@lru_cache(maxsize=1)
def get_analyze_case_service() -> AnalyzeCaseService:
    return AnalyzeCaseService(get_north_gateway())


@lru_cache(maxsize=1)
def get_legal_conversation_service() -> LegalConversationService:
    return LegalConversationService(get_north_gateway())


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
def get_persistent_conversation_service() -> PersistentLegalConversationService:
    return PersistentLegalConversationService(
        get_session_factory(),
        get_personal_user_context(),
        get_north_gateway(),
        get_embedding_gateway(),
        get_legal_knowledge_port(),
        get_case_law_knowledge_port(),
    )
