from __future__ import annotations

import pytest

from lexora_ai.application import (
    ConversationCaseLawChunk,
    ConversationEvidenceChunk,
    ConversationLegalChunk,
)
from lexora_ai.infrastructure.north_tools import build_lexora_tools


class RecordingRetrieval:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search_materials(self, query: str):
        self.calls.append(("materials", query))
        return (
            ConversationEvidenceChunk(
                reference="M1:C1",
                material_id="material-1",
                title="劳动合同",
                kind="contract",
                source_note=None,
                content="劳动合同内容",
            ),
        )

    async def search_legal_authorities(self, query: str):
        self.calls.append(("legal", query))
        return (
            ConversationLegalChunk(
                reference="L1:C1",
                title="中华人民共和国测试法",
                article_label="第一条",
                issuing_authority="全国人民代表大会",
                source_url="https://flk.npc.gov.cn/detail?id=test",
                status="effective",
                content="测试规则",
            ),
        )

    async def search_case_law(self, query: str):
        self.calls.append(("cases", query))
        return (
            ConversationCaseLawChunk(
                reference="C1:S1",
                case_number="指导案例1号",
                title="测试案例",
                section_label="裁判理由",
                issuing_authority="最高人民法院",
                source_url="https://www.court.gov.cn/test",
                published_on="2026-01-01",
                content="测试裁判理由",
            ),
        )


def test_without_retrieval_only_deterministic_calculation_is_exposed() -> None:
    tools = {tool.name: tool for tool in build_lexora_tools(None)}

    assert set(tools) == {"calculate_employment_termination_compensation"}


@pytest.mark.asyncio
async def test_retrieval_tools_keep_source_types_separate() -> None:
    retrieval = RecordingRetrieval()
    tools = {tool.name: tool for tool in build_lexora_tools(retrieval)}

    assert set(tools) == {
        "calculate_employment_termination_compensation",
        "search_case_materials",
        "search_legal_authorities",
        "search_guiding_cases",
    }

    materials = await tools["search_case_materials"].ainvoke({"query": "劳动合同期限"})
    authorities = await tools["search_legal_authorities"].ainvoke(
        {"query": "解除劳动合同的补偿规则"}
    )
    cases = await tools["search_guiding_cases"].ainvoke({"query": "违法解除类案"})

    assert materials["retrieved_material_chunks"][0]["reference"] == "M1:C1"
    assert authorities["legal_authorities"][0]["article_label"] == "第一条"
    assert cases["case_law_authorities"][0]["case_number"] == "指导案例1号"
    assert retrieval.calls == [
        ("materials", "劳动合同期限"),
        ("legal", "解除劳动合同的补偿规则"),
        ("cases", "违法解除类案"),
    ]


@pytest.mark.asyncio
async def test_authority_search_has_a_hard_per_turn_budget() -> None:
    retrieval = RecordingRetrieval()
    tool = {tool.name: tool for tool in build_lexora_tools(retrieval)}[
        "search_legal_authorities"
    ]

    for index in range(5):
        result = await tool.ainvoke({"query": f"法规查询{index}"})
        assert result["search_limit_reached"] is False
    exhausted = await tool.ainvoke({"query": "超出预算"})

    assert exhausted == {
        "legal_authorities": [],
        "search_limit_reached": True,
        "remaining_searches": 0,
    }
    assert len(retrieval.calls) == 5


def test_employment_compensation_tool_returns_exact_n_and_2n() -> None:
    tool = {tool.name: tool for tool in build_lexora_tools(None)}[
        "calculate_employment_termination_compensation"
    ]

    result = tool.invoke(
        {
            "completed_years": 3,
            "additional_months": 2,
            "monthly_wage": "10000",
        }
    )

    assert result["compensation_months"] == "3.50"
    assert result["economic_compensation_n"] == "35000.00"
    assert result["unlawful_termination_damages_2n"] == "70000.00"
