from __future__ import annotations

from lexora_ai.domain import CaseMaterial
from lexora_ai.material_context import (
    MaterialContextChunk,
    build_material_context,
    rank_material_context,
    retrieve_material_context,
)


def test_material_context_uses_rag_core_chunks_with_stable_references() -> None:
    material = CaseMaterial(
        title="长篇陈述",
        content="。".join(f"第 {index} 项事实" for index in range(1, 800)),
    )

    chunks = build_material_context([material])

    assert len(chunks) > 1
    assert chunks[0].reference == "M1:C1"
    assert chunks[1].reference == "M1:C2"
    assert all(chunk.material_id == str(material.material_id) for chunk in chunks)


def test_material_retrieval_returns_only_relevant_chunks() -> None:
    materials = [
        CaseMaterial(title="工资记录", content="公司已经连续三个月拖欠工资，尚未支付。"),
        CaseMaterial(title="车辆记录", content="车辆发生碰撞后在维修厂更换了保险杠。"),
    ]

    chunks = retrieve_material_context("公司拖欠工资怎么办", materials, top_k=1)

    assert [chunk.reference for chunk in chunks] == ["M1:C1"]
    assert "拖欠工资" in chunks[0].content


def test_material_retrieval_returns_no_chunks_without_a_lexical_match() -> None:
    materials = [CaseMaterial(title="租赁合同", content="租期为两年，每月支付租金。")]

    assert retrieve_material_context("交通事故责任", materials) == []


def test_hybrid_retrieval_can_recall_a_semantic_match_without_shared_terms() -> None:
    chunks = [
        MaterialContextChunk(
            reference="M1:C1",
            material_id="wages",
            title="工资记录",
            kind="evidence",
            source_note=None,
            content="用人单位连续三个月拖欠劳动报酬。",
            page_start=None,
            page_end=None,
            embedding=(1.0, 0.0),
            embedding_model="test-embedding",
        ),
        MaterialContextChunk(
            reference="M2:C1",
            material_id="vehicle",
            title="车辆记录",
            kind="evidence",
            source_note=None,
            content="车辆在维修厂更换了保险杠。",
            page_start=None,
            page_end=None,
            embedding=(0.0, 1.0),
            embedding_model="test-embedding",
        ),
    ]

    hits = rank_material_context(
        "薪资一直没有到账",
        chunks,
        top_k=1,
        query_embedding=(0.95, 0.05),
        embedding_model="test-embedding",
    )

    assert [hit.reference for hit in hits] == ["M1:C1"]
