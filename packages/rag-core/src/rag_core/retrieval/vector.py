from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import sqrt

from rag_core.retrieval.contracts import (
    EmbeddedRetrievalDocument,
    RetrievalDocument,
    RetrievalHit,
)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right:
        raise ValueError("embeddings must not be empty")
    if len(left) != len(right):
        raise ValueError("embedding dimensions must match")

    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def rank_vector_documents(
    query_embedding: Sequence[float],
    documents: Iterable[EmbeddedRetrievalDocument],
    *,
    top_k: int,
) -> list[RetrievalHit]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not query_embedding:
        raise ValueError("query_embedding must not be empty")

    scored: list[tuple[float, int, int, RetrievalDocument]] = []
    for source_order, item in enumerate(documents):
        score = cosine_similarity(query_embedding, item.embedding)
        if score <= 0:
            continue
        scored.append((score, len(item.document.content), source_order, item.document))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [
        RetrievalHit(document=document, score=score, rank=rank)
        for rank, (score, _, _, document) in enumerate(scored[:top_k], start=1)
    ]


def fuse_retrieval_hits(
    rankings: Iterable[Iterable[RetrievalHit]],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[RetrievalHit]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if rank_constant < 0:
        raise ValueError("rank_constant must not be negative")

    documents: dict[str, RetrievalDocument] = {}
    scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    matched_terms: dict[str, list[str]] = {}
    seen_order = 0

    for ranking in rankings:
        for hit in ranking:
            document_id = hit.document.id
            documents.setdefault(document_id, hit.document)
            first_seen.setdefault(document_id, seen_order)
            seen_order += 1
            scores[document_id] = scores.get(document_id, 0.0) + 1.0 / (
                rank_constant + hit.rank
            )
            best_ranks[document_id] = min(best_ranks.get(document_id, hit.rank), hit.rank)
            terms = matched_terms.setdefault(document_id, [])
            terms.extend(term for term in hit.matched_terms if term not in terms)

    ordered_ids = sorted(
        documents,
        key=lambda document_id: (
            -scores[document_id],
            best_ranks[document_id],
            first_seen[document_id],
        ),
    )[:top_k]
    return [
        RetrievalHit(
            document=documents[document_id],
            score=scores[document_id],
            rank=rank,
            matched_terms=tuple(matched_terms[document_id]),
        )
        for rank, document_id in enumerate(ordered_ids, start=1)
    ]
