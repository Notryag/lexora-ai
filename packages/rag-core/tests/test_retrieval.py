from __future__ import annotations

import pytest

from rag_core import (
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


def test_query_terms_supports_latin_and_cjk_without_product_stop_words() -> None:
    terms = query_terms("OpenAI 合同违约")

    assert "openai" in terms
    assert "合同" in terms
    assert "违约" in terms
    assert "合同违约" in terms


def test_query_terms_accepts_application_owned_stop_terms() -> None:
    terms = query_terms("怎么处理合同违约", stop_terms={"怎么", "处理"})

    assert "怎么" not in terms
    assert "处理" not in terms
    assert "合同" in terms


def test_lexical_score_is_case_insensitive() -> None:
    assert lexical_score("OpenAI contract", "OPENAI contract terms") == 4.0


def test_rank_lexical_documents_excludes_zero_matches_and_is_deterministic() -> None:
    documents = [
        RetrievalDocument(id="long", content="合同违约后应当承担相应责任和损失"),
        RetrievalDocument(id="short", content="合同违约"),
        RetrievalDocument(id="irrelevant", content="天气晴朗"),
    ]

    hits = rank_lexical_documents("合同违约", documents, top_k=3)

    assert [hit.document.id for hit in hits] == ["short", "long"]
    assert [hit.rank for hit in hits] == [1, 2]
    assert all(hit.score > 0 for hit in hits)
    assert "合同违约" in hits[0].matched_terms


def test_rank_lexical_documents_validates_top_k() -> None:
    with pytest.raises(ValueError, match="top_k must be positive"):
        rank_lexical_documents("query", [], top_k=0)


def test_rank_vector_documents_orders_by_cosine_similarity() -> None:
    documents = [
        EmbeddedRetrievalDocument(
            RetrievalDocument(id="wages", content="拖欠工资"),
            (1.0, 0.0),
        ),
        EmbeddedRetrievalDocument(
            RetrievalDocument(id="weather", content="天气晴朗"),
            (0.0, 1.0),
        ),
    ]

    hits = rank_vector_documents((0.9, 0.1), documents, top_k=2)

    assert [hit.document.id for hit in hits] == ["wages", "weather"]
    assert hits[0].score > hits[1].score


def test_cosine_similarity_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="dimensions must match"):
        cosine_similarity((1.0,), (1.0, 2.0))


def test_fuse_retrieval_hits_rewards_documents_found_by_both_rankings() -> None:
    first = RetrievalDocument(id="first", content="first")
    shared = RetrievalDocument(id="shared", content="shared")
    lexical = [
        RetrievalHit(document=first, score=4.0, rank=1, matched_terms=("term",)),
        RetrievalHit(document=shared, score=2.0, rank=2),
    ]
    vector = [RetrievalHit(document=shared, score=0.9, rank=1)]

    hits = fuse_retrieval_hits([lexical, vector], top_k=2)

    assert [hit.document.id for hit in hits] == ["shared", "first"]
    assert hits[1].matched_terms == ("term",)
