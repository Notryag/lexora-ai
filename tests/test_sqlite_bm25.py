from __future__ import annotations

import pytest
from rag_core import RetrievalDocument

from lexora_ai.infrastructure.sqlite_bm25 import SqliteBm25Index


def test_sqlite_bm25_index_is_bounded_ranked_and_reusable(tmp_path) -> None:
    index = SqliteBm25Index(tmp_path / "bm25.sqlite3")
    documents = [
        RetrievalDocument(id="contract", content="合同违约应承担赔偿责任"),
        RetrievalDocument(id="marriage", content="婚姻关系与离婚登记"),
    ]

    built = index.build(documents, corpus_identity="sha256:fixture")
    hits = index.search("合同赔偿", top_k=2)
    reused = index.build([], corpus_identity="sha256:fixture")

    assert built.document_count == 2
    assert not built.reused
    assert hits[0].document_id == "contract"
    assert hits[0].rank == 1
    assert reused.reused


def test_sqlite_bm25_index_rejects_resource_overflow_and_identity_mismatch(tmp_path) -> None:
    limited = SqliteBm25Index(tmp_path / "limited.sqlite3")
    with pytest.raises(ValueError, match="max_documents"):
        limited.build(
            [
                RetrievalDocument(id="one", content="第一份文档"),
                RetrievalDocument(id="two", content="第二份文档"),
            ],
            corpus_identity="fixture",
            max_documents=1,
        )
    assert not limited.path.exists()

    index = SqliteBm25Index(tmp_path / "identity.sqlite3")
    index.build(
        [RetrievalDocument(id="one", content="第一份文档")],
        corpus_identity="first",
    )
    with pytest.raises(ValueError, match="different corpus identity"):
        index.build([], corpus_identity="second")

    with pytest.raises(ValueError, match="max_query_chars"):
        index.search("合同" * 501)
