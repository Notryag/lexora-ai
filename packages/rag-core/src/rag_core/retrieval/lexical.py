from __future__ import annotations

import re
from collections.abc import Iterable

from rag_core.retrieval.contracts import RetrievalDocument, RetrievalHit

_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
DEFAULT_CJK_NGRAM_SIZES = (2, 3, 4)


def query_terms(
    query: str,
    *,
    stop_terms: Iterable[str] = (),
    cjk_ngram_sizes: tuple[int, ...] = DEFAULT_CJK_NGRAM_SIZES,
) -> list[str]:
    if any(size <= 0 for size in cjk_ngram_sizes):
        raise ValueError("cjk_ngram_sizes must contain only positive integers")

    normalized_stop_terms = {term.lower() for term in stop_terms}
    terms = [match.group(0).lower() for match in _LATIN_TOKEN_RE.finditer(query)]
    for match in _CJK_RUN_RE.finditer(query):
        run = match.group(0).lower()
        for size in cjk_ngram_sizes:
            if len(run) < size:
                continue
            terms.extend(run[index : index + size] for index in range(len(run) - size + 1))

    return list(dict.fromkeys(term for term in terms if term not in normalized_stop_terms))


def lexical_score(
    query: str,
    content: str,
    *,
    stop_terms: Iterable[str] = (),
    cjk_ngram_sizes: tuple[int, ...] = DEFAULT_CJK_NGRAM_SIZES,
) -> float:
    normalized_content = content.lower()
    return float(
        sum(
            2 if len(term) >= 3 else 1
            for term in query_terms(
                query,
                stop_terms=stop_terms,
                cjk_ngram_sizes=cjk_ngram_sizes,
            )
            if term in normalized_content
        )
    )


def rank_lexical_documents(
    query: str,
    documents: Iterable[RetrievalDocument],
    *,
    top_k: int,
    stop_terms: Iterable[str] = (),
    cjk_ngram_sizes: tuple[int, ...] = DEFAULT_CJK_NGRAM_SIZES,
) -> list[RetrievalHit]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    terms = query_terms(
        query,
        stop_terms=stop_terms,
        cjk_ngram_sizes=cjk_ngram_sizes,
    )
    scored: list[tuple[float, int, int, RetrievalDocument, tuple[str, ...]]] = []
    for source_order, document in enumerate(documents):
        normalized_content = document.content.lower()
        matched_terms = tuple(term for term in terms if term in normalized_content)
        score = float(sum(2 if len(term) >= 3 else 1 for term in matched_terms))
        if score <= 0:
            continue
        scored.append((score, len(document.content), source_order, document, matched_terms))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [
        RetrievalHit(
            document=document,
            score=score,
            rank=rank,
            matched_terms=matched_terms,
        )
        for rank, (score, _, _, document, matched_terms) in enumerate(scored[:top_k], start=1)
    ]
