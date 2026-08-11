"""Framework-neutral RAG primitives."""

from rag_core.ingestion import (
    ChunkDraft,
    ChunkingPolicy,
    DocumentBlock,
    DocumentSplitter,
    HeuristicTokenEstimator,
    HierarchicalSplitter,
    IngestionChunk,
    ParsedDocument,
    RecursiveFallbackSplitter,
    SlicingTokenEstimator,
    SplitterRegistry,
    TokenEstimator,
    default_splitter_registry,
    split_text_to_limit,
)
from rag_core.retrieval import (
    DEFAULT_CJK_NGRAM_SIZES,
    EmbeddedRetrievalDocument,
    RetrievalDocument,
    RetrievalHit,
    cosine_similarity,
    fuse_retrieval_hits,
    lexical_score,
    query_terms,
    rank_lexical_documents,
    rank_vector_documents,
)

__version__ = "0.1.0"

__all__ = [
    "ChunkDraft",
    "ChunkingPolicy",
    "DEFAULT_CJK_NGRAM_SIZES",
    "DocumentBlock",
    "DocumentSplitter",
    "EmbeddedRetrievalDocument",
    "HeuristicTokenEstimator",
    "HierarchicalSplitter",
    "IngestionChunk",
    "ParsedDocument",
    "RecursiveFallbackSplitter",
    "RetrievalDocument",
    "RetrievalHit",
    "SlicingTokenEstimator",
    "SplitterRegistry",
    "TokenEstimator",
    "cosine_similarity",
    "default_splitter_registry",
    "fuse_retrieval_hits",
    "lexical_score",
    "query_terms",
    "rank_lexical_documents",
    "rank_vector_documents",
    "split_text_to_limit",
]
