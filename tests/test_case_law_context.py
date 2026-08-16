from uuid import uuid4

from lexora_ai.case_law_context import rank_case_law
from lexora_ai.domain import CaseLawChunk
from lexora_ai.evaluation.case_law_retrieval import _load_cases


def _chunk(*, content: str, embedding: list[float] | None = None) -> CaseLawChunk:
    return CaseLawChunk(
        id=uuid4(),
        source_id=uuid4(),
        reference=f"C{uuid4().hex}:S1",
        section_label="裁判要旨",
        case_number="入库编号 2025-01-1-000-001",
        title="测试案例",
        keywords=[],
        issuing_authority="测试法院",
        source_url="https://www.court.gov.cn/zixun/xiangqing/1.html",
        published_on=None,
        content=content,
        embedding=embedding,
        embedding_model="test-embedding" if embedding is not None else None,
    )


def test_question_words_do_not_create_unrelated_lexical_hits() -> None:
    chunks = [_chunk(content="本案争议焦点为该行为是否构成违约。")]

    assert (
        rank_case_law(
            "夫妻分居多年是否自动离婚",
            chunks,
            query_embedding=None,
            embedding_model=None,
        )
        == []
    )


def test_weak_vector_similarity_is_rejected_without_lexical_support() -> None:
    chunks = [_chunk(content="劳动合同解除纠纷", embedding=[1.0, 0.0])]

    assert (
        rank_case_law(
            "夫妻离婚",
            chunks,
            query_embedding=(0.5, 0.8660254),
            embedding_model="test-embedding",
        )
        == []
    )


def test_strong_vector_similarity_remains_retrievable() -> None:
    chunk = _chunk(content="夫妻离婚财产分割", embedding=[1.0, 0.0])

    assert rank_case_law(
        "婚姻关系解除",
        [chunk],
        query_embedding=(1.0, 0.0),
        embedding_model="test-embedding",
    ) == [chunk]


def test_default_case_law_evaluation_dataset_is_packaged() -> None:
    cases = _load_cases(None)

    assert len(cases) == 12
    assert any(case.id == "bigamy-spousal-cohabitation" for case in cases)
