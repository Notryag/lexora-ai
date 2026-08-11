"""Document ingestion contracts and deterministic splitting."""

from rag_core.ingestion.contracts import ChunkDraft, DocumentBlock, IngestionChunk, ParsedDocument
from rag_core.ingestion.policies import ChunkingPolicy
from rag_core.ingestion.registry import SplitterRegistry, default_splitter_registry
from rag_core.ingestion.splitting import (
    DocumentSplitter,
    HierarchicalSplitter,
    RecursiveFallbackSplitter,
    split_text_to_limit,
)
from rag_core.ingestion.token_estimation import (
    HeuristicTokenEstimator,
    SlicingTokenEstimator,
    TokenEstimator,
)

__all__ = [
    "ChunkDraft",
    "ChunkingPolicy",
    "DocumentBlock",
    "DocumentSplitter",
    "HeuristicTokenEstimator",
    "HierarchicalSplitter",
    "IngestionChunk",
    "ParsedDocument",
    "RecursiveFallbackSplitter",
    "SlicingTokenEstimator",
    "SplitterRegistry",
    "TokenEstimator",
    "default_splitter_registry",
    "split_text_to_limit",
]
