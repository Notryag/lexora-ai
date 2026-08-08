"""Infrastructure adapters."""

from lexora_ai.infrastructure.database_case_law import DatabaseCaseLawKnowledgePort
from lexora_ai.infrastructure.database_legal_knowledge import DatabaseLegalKnowledgePort
from lexora_ai.infrastructure.lvyan_lawtext import (
    LvyanLawTextConnector,
    LvyanLawTextError,
)
from lexora_ai.infrastructure.material_parser import parse_material_file
from lexora_ai.infrastructure.north_gateway import (
    ModelNotConfiguredError,
    NorthCaseAnalysisGateway,
)
from lexora_ai.infrastructure.openai_embeddings import OpenAIEmbeddingGateway
from lexora_ai.infrastructure.spc_guiding_cases import (
    SpcGuidingCaseConnector,
    SpcGuidingCaseError,
)

__all__ = [
    "ModelNotConfiguredError",
    "DatabaseCaseLawKnowledgePort",
    "DatabaseLegalKnowledgePort",
    "NorthCaseAnalysisGateway",
    "LvyanLawTextConnector",
    "LvyanLawTextError",
    "OpenAIEmbeddingGateway",
    "SpcGuidingCaseConnector",
    "SpcGuidingCaseError",
    "parse_material_file",
]
