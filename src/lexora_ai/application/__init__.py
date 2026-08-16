"""Lexora application use cases."""

from lexora_ai.application.analyze_case import AnalyzeCaseService
from lexora_ai.application.case_context import CaseContextService
from lexora_ai.application.case_law_sources import CaseLawSourceService
from lexora_ai.application.case_law_sync import (
    CaseLawConnector,
    CaseLawSourceLocator,
    CaseLawSyncResult,
    CaseLawSyncService,
    parse_case_law_manifest,
)
from lexora_ai.application.case_runs import CaseRunService
from lexora_ai.application.case_workspace import CaseWorkspaceService
from lexora_ai.application.converse import LegalConversationService
from lexora_ai.application.errors import (
    ActiveCaseRunNotFoundError,
    CaseNotFoundError,
    DuplicateLegalSourceError,
    EmbeddingUnavailableError,
    LegalSourceNotFoundError,
    MaterialLimitError,
    MaterialNotFoundError,
    MaterialParseError,
    RunCancelledError,
)
from lexora_ai.application.legal_source_sync import (
    LegalSourceConnector,
    LegalSourceSyncResult,
    LegalSourceSyncService,
)
from lexora_ai.application.legal_sources import LegalSourceService
from lexora_ai.application.persistent_conversation import PersistentLegalConversationService
from lexora_ai.application.ports import (
    CaseAnalysisGateway,
    CaseLawKnowledgePort,
    ConversationCaseLawChunk,
    ConversationCaseMemoryPort,
    ConversationContextMessage,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
    ConversationRetrievalPort,
    EmbeddingGateway,
    FactorUpdateReviewerPort,
    FollowUpReviewerPort,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
    LegalConversationGateway,
    LegalKnowledgePort,
)
from lexora_ai.application.run_journal import ProjectedRunEvent, RunJournal, project_runtime_event

__all__ = [
    "AnalyzeCaseService",
    "ActiveCaseRunNotFoundError",
    "CaseAnalysisGateway",
    "CaseLawConnector",
    "CaseLawSourceLocator",
    "CaseLawKnowledgePort",
    "CaseLawSourceService",
    "CaseLawSyncResult",
    "CaseLawSyncService",
    "parse_case_law_manifest",
    "CaseRunService",
    "CaseNotFoundError",
    "CaseWorkspaceService",
    "CaseContextService",
    "ConversationContextMessage",
    "ConversationCaseLawChunk",
    "ConversationCaseMemoryPort",
    "ConversationEvidenceChunk",
    "ConversationLegalChunk",
    "ConversationRetrievalPort",
    "DuplicateLegalSourceError",
    "EmbeddingGateway",
    "EmbeddingUnavailableError",
    "FactorUpdateReviewerPort",
    "FollowUpReviewerPort",
    "GeneratedCaseAnalysis",
    "GeneratedConversationTurn",
    "LegalConversationGateway",
    "LegalKnowledgePort",
    "LegalConversationService",
    "LegalSourceNotFoundError",
    "LegalSourceConnector",
    "LegalSourceSyncResult",
    "LegalSourceSyncService",
    "LegalSourceService",
    "MaterialLimitError",
    "MaterialNotFoundError",
    "MaterialParseError",
    "PersistentLegalConversationService",
    "ProjectedRunEvent",
    "RunJournal",
    "project_runtime_event",
    "RunCancelledError",
]
