from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from lexora_ai.domain import CaseLawChunk, LegalKnowledgeChunk, LegalSourceStatus
from lexora_ai.infrastructure.database_case_law import DatabaseCaseLawKnowledgePort
from lexora_ai.infrastructure.database_legal_knowledge import DatabaseLegalKnowledgePort


class FakePostgresSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))


@pytest.mark.asyncio
async def test_postgres_legal_retrieval_hydrates_only_bounded_candidates(monkeypatch) -> None:
    lexical_id = uuid4()
    vector_id = uuid4()
    source_id = uuid4()
    lightweight_chunks = [
        LegalKnowledgeChunk(
            id=lexical_id,
            source_id=source_id,
            reference="L1:C1",
            article_label="第一条",
            title="劳动合同法",
            issuing_authority="全国人大常委会",
            source_url="https://example.test/labor",
            status=LegalSourceStatus.effective,
            content="解除劳动合同应当支付经济补偿。",
            embedding_model="test-model",
        ),
        LegalKnowledgeChunk(
            id=vector_id,
            source_id=source_id,
            reference="L1:C2",
            article_label="第二条",
            title="劳动合同法",
            issuing_authority="全国人大常委会",
            source_url="https://example.test/labor",
            status=LegalSourceStatus.effective,
            content="其他规定。",
            embedding_model="test-model",
        ),
    ]
    hydrated_chunks = [
        lightweight_chunks[0].model_copy(update={"embedding": [0.0, 1.0]}),
        lightweight_chunks[1].model_copy(update={"embedding": [1.0, 0.0]}),
    ]

    class FakeRepository:
        def __init__(self) -> None:
            self.loads = []

        async def list_effective_chunks(
            self, *, include_embeddings=True, chunk_ids=None, limit=None
        ):
            self.loads.append((include_embeddings, chunk_ids, limit))
            if chunk_ids is None:
                assert include_embeddings is False
                return lightweight_chunks
            return [chunk for chunk in hydrated_chunks if chunk.id in chunk_ids]

        async def list_effective_vector_candidate_ids(
            self, query_embedding, embedding_model, *, limit
        ):
            assert query_embedding == (1.0, 0.0)
            assert embedding_model == "test-model"
            assert limit == 6
            return [vector_id]

    repository = FakeRepository()
    monkeypatch.setattr(
        "lexora_ai.infrastructure.database_legal_knowledge.LexoraUnitOfWork",
        lambda session: SimpleNamespace(legal_sources=repository),
    )
    port = DatabaseLegalKnowledgePort(lambda: FakePostgresSession())

    result = await port.search(
        "经济补偿",
        query_embedding=(1.0, 0.0),
        embedding_model="test-model",
        top_k=2,
    )

    assert {chunk.id for chunk in result} == {lexical_id, vector_id}
    assert repository.loads[0] == (False, None, 10_001)
    assert repository.loads[1][0] is True
    assert set(repository.loads[1][1]) == {lexical_id, vector_id}


@pytest.mark.asyncio
async def test_postgres_case_law_retrieval_hydrates_only_bounded_candidates(monkeypatch) -> None:
    lexical_id = uuid4()
    vector_id = uuid4()
    source_id = uuid4()
    lightweight_chunks = [
        CaseLawChunk(
            id=lexical_id,
            source_id=source_id,
            reference="C1:S1",
            section_label="裁判要旨",
            case_number="（2026）测1号",
            title="劳动争议案",
            keywords=["经济补偿"],
            issuing_authority="测试法院",
            source_url="https://example.test/case",
            published_on=None,
            content="解除劳动合同经济补偿。",
            embedding_model="test-model",
        ),
        CaseLawChunk(
            id=vector_id,
            source_id=source_id,
            reference="C1:S2",
            section_label="裁判理由",
            case_number="（2026）测1号",
            title="劳动争议案",
            keywords=[],
            issuing_authority="测试法院",
            source_url="https://example.test/case",
            published_on=None,
            content="其他裁判理由。",
            embedding_model="test-model",
        ),
    ]
    hydrated_chunks = [
        lightweight_chunks[0].model_copy(update={"embedding": [0.0, 1.0]}),
        lightweight_chunks[1].model_copy(update={"embedding": [1.0, 0.0]}),
    ]

    class FakeRepository:
        def __init__(self) -> None:
            self.loads = []

        async def list_approved_chunks(
            self, *, include_embeddings=True, chunk_ids=None, limit=None
        ):
            self.loads.append((include_embeddings, chunk_ids, limit))
            if chunk_ids is None:
                assert include_embeddings is False
                return lightweight_chunks
            return [chunk for chunk in hydrated_chunks if chunk.id in chunk_ids]

        async def list_approved_vector_candidate_ids(
            self, query_embedding, embedding_model, *, limit
        ):
            assert query_embedding == (1.0, 0.0)
            assert embedding_model == "test-model"
            assert limit == 6
            return [vector_id]

    repository = FakeRepository()
    monkeypatch.setattr(
        "lexora_ai.infrastructure.database_case_law.LexoraUnitOfWork",
        lambda session: SimpleNamespace(case_law=repository),
    )
    port = DatabaseCaseLawKnowledgePort(lambda: FakePostgresSession())

    result = await port.search(
        "经济补偿",
        query_embedding=(1.0, 0.0),
        embedding_model="test-model",
        top_k=2,
    )

    assert {chunk.id for chunk in result} == {lexical_id, vector_id}
    assert repository.loads[0] == (False, None, 10_001)
    assert repository.loads[1][0] is True
    assert set(repository.loads[1][1]) == {lexical_id, vector_id}
