from uuid import UUID, uuid4

from lexora_ai.case_law_context import rank_case_law
from lexora_ai.domain import CaseLawChunk
from lexora_ai.evaluation.case_law_retrieval import _load_cases


def _chunk(
    *,
    content: str,
    embedding: list[float] | None = None,
    source_id: UUID | None = None,
) -> CaseLawChunk:
    return CaseLawChunk(
        id=uuid4(),
        source_id=source_id or uuid4(),
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


def test_incidental_lexical_overlap_is_rejected_for_long_queries() -> None:
    chunks = [_chunk(content="裁判应当遵循相关原则。")]

    assert (
        rank_case_law(
            "量子计算机专利侵权中的等同原则",
            chunks,
            query_embedding=None,
            embedding_model=None,
        )
        == []
    )


def test_short_exact_legal_term_remains_retrievable() -> None:
    chunk = _chunk(content="被告人的行为构成重婚罪。")

    assert rank_case_law(
        "重婚",
        [chunk],
        query_embedding=None,
        embedding_model=None,
    ) == [chunk]


def test_results_include_at_most_two_chunks_per_case_source() -> None:
    repeated_source_id = uuid4()
    first = _chunk(content="夫妻共同财产分割。", source_id=repeated_source_id)
    second = _chunk(content="离婚时分割共同财产。", source_id=repeated_source_id)
    third = _chunk(content="离婚共同财产由双方协议处理。", source_id=repeated_source_id)
    other = _chunk(content="离婚时一方隐藏共同财产可以少分。")

    result = rank_case_law(
        "离婚共同财产分割隐藏财产",
        [first, second, third, other],
        query_embedding=None,
        embedding_model=None,
    )

    assert len(result) == 3
    assert {chunk.source_id for chunk in result} == {repeated_source_id, other.source_id}
    assert sum(chunk.source_id == repeated_source_id for chunk in result) == 2


def test_default_case_law_evaluation_dataset_is_packaged() -> None:
    cases = _load_cases(None)

    assert len(cases) == 12
    assert any(case.id == "bigamy-spousal-cohabitation" for case in cases)
