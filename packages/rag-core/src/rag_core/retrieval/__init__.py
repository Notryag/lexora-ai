"""Framework-neutral retrieval contracts and deterministic algorithms."""

from rag_core.retrieval.contracts import (
    EmbeddedRetrievalDocument,
    RetrievalDocument,
    RetrievalHit,
)
from rag_core.retrieval.lexical import (
    DEFAULT_CJK_NGRAM_SIZES,
    lexical_score,
    query_terms,
    rank_lexical_documents,
)
from rag_core.retrieval.vector import (
    cosine_similarity,
    fuse_retrieval_hits,
    rank_vector_documents,
)

__all__ = [
    "DEFAULT_CJK_NGRAM_SIZES",
    "EmbeddedRetrievalDocument",
    "RetrievalDocument",
    "RetrievalHit",
    "cosine_similarity",
    "fuse_retrieval_hits",
    "lexical_score",
    "query_terms",
    "rank_lexical_documents",
    "rank_vector_documents",
]
