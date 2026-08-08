from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from lexora_ai.domain import (
    LegalKnowledgeChunk,
    LegalSourceCreate,
    LegalSourceKind,
    LegalSourceStatus,
)
from lexora_ai.legal_context import rank_legal_knowledge, split_legal_source


def test_legal_source_requires_an_official_government_https_url() -> None:
    with pytest.raises(ValidationError, match="official HTTPS"):
        LegalSourceCreate(
            title="测试法规",
            kind=LegalSourceKind.law,
            issuing_authority="测试机关",
            status=LegalSourceStatus.effective,
            source_name="非官方网站",
            source_url="https://example.com/law",
            content="第一条 测试内容。",
        )


def test_legal_source_splitter_preserves_article_boundaries() -> None:
    source = LegalSourceCreate(
        title="测试法规",
        kind=LegalSourceKind.law,
        issuing_authority="测试机关",
        status=LegalSourceStatus.effective,
        source_name="国家法律法规数据库",
        source_url="https://flk.npc.gov.cn/detail?id=test",
        content="第一条 第一项规则。\n第二条 第二项规则。",
    )

    chunks = split_legal_source(uuid4(), source.title, source.content)

    assert [chunk.article_label for chunk in chunks] == ["第一条", "第二条"]
    assert chunks[0].content.startswith("第一条")


def test_legal_retrieval_prioritizes_exact_article_in_named_law() -> None:
    chunks = [
        _knowledge_chunk(
            title="中华人民共和国劳动法",
            article_label="第三十八条",
            content="第三十八条 用人单位应当保证劳动者每周至少休息一日。",
        ),
        _knowledge_chunk(
            title="中华人民共和国劳动合同法",
            article_label="第三十八条",
            content="第三十八条 用人单位未及时足额支付劳动报酬的，劳动者可以解除劳动合同。",
        ),
        _knowledge_chunk(
            title="中华人民共和国劳动合同法",
            article_label="第四十六条",
            content="第四十六条 劳动者依照本法第三十八条解除劳动合同的，应支付补偿。",
        ),
    ]

    ranked = rank_legal_knowledge(
        "劳动合同法第三十八条规定了什么？",
        chunks,
        query_embedding=None,
        embedding_model=None,
        top_k=3,
    )

    assert ranked[0].title == "中华人民共和国劳动合同法"
    assert ranked[0].article_label == "第三十八条"


def test_legal_retrieval_expands_everyday_wage_language() -> None:
    chunks = [
        _knowledge_chunk(
            title="中华人民共和国劳动合同法",
            article_label="第三十八条",
            content="第三十八条 用人单位未及时足额支付劳动报酬的，劳动者可以解除劳动合同。",
        ),
        _knowledge_chunk(
            title="中华人民共和国劳动合同法",
            article_label="第四十六条",
            content="第四十六条 劳动者依照本法第三十八条解除劳动合同的，应支付补偿。",
        ),
    ]

    ranked = rank_legal_knowledge(
        "公司拖欠工资，我可以解除劳动合同并要求补偿吗？",
        chunks,
        query_embedding=None,
        embedding_model=None,
        top_k=2,
    )

    assert {chunk.article_label for chunk in ranked} == {"第三十八条", "第四十六条"}


def _knowledge_chunk(*, title: str, article_label: str, content: str) -> LegalKnowledgeChunk:
    source_id = uuid4()
    return LegalKnowledgeChunk(
        id=uuid4(),
        source_id=source_id,
        reference=f"{source_id}:{article_label}",
        article_label=article_label,
        heading_path=("第一章 测试",),
        title=title,
        issuing_authority="全国人民代表大会常务委员会",
        source_url=f"https://flk.npc.gov.cn/detail?id={source_id}",
        status=LegalSourceStatus.effective,
        content=content,
    )
