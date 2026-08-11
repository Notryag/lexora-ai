from __future__ import annotations

import asyncio

import pytest

from lexora_ai.application import ConversationLegalChunk
from lexora_ai.domain import CaseProfile
from lexora_ai.infrastructure.north_tools import build_lexora_tools


class RecordingRetrieval:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def search_materials(self, query: str):
        self.calls.append(("materials", query))
        return ()

    async def search_legal_authorities(self, query: str):
        self.calls.append(("legal", query))
        return (
            ConversationLegalChunk(
                reference=f"L{len(self.calls)}:C1",
                title="中华人民共和国测试法",
                article_label="第一条",
                issuing_authority="全国人民代表大会",
                source_url="https://flk.npc.gov.cn/detail?id=test",
                status="effective",
                content=f"与{query}有关的规则",
            ),
        )

    async def search_case_law(self, query: str):
        self.calls.append(("cases", query))
        return ()


class RankedRetrieval(RecordingRetrieval):
    async def search_legal_authorities(self, query: str):
        self.calls.append(("legal", query))
        query_number = len(self.calls)
        return tuple(
            ConversationLegalChunk(
                reference=f"L{query_number}:C{rank}",
                title="中华人民共和国测试法",
                article_label=f"第{rank}条",
                issuing_authority="全国人民代表大会",
                source_url="https://flk.npc.gov.cn/detail?id=test",
                status="effective",
                content=f"{query}的第{rank}项规则",
            )
            for rank in range(1, 14)
        )


class RecordingCaseMemory:
    def __init__(self) -> None:
        self.profile = CaseProfile(missing_information=["房屋购买时间"])
        self.patches = []

    async def get_profile(self):
        return self.profile.model_copy(deep=True)

    async def update_profile(self, patch):
        self.patches.append(patch)
        self.profile = patch.apply(self.profile)
        return self.profile


@pytest.mark.asyncio
async def test_agent_retrieval_tools_keep_sources_separate() -> None:
    retrieval = RecordingRetrieval()
    tools = {
        tool.name: tool for tool in build_lexora_tools(retrieval, None, user_message="解除劳动合同")
    }

    assert set(tools) == {
        "prepare_legal_turn",
        "search_case_materials",
        "search_legal_authorities",
        "search_guiding_cases",
    }

    result = await tools["search_legal_authorities"].ainvoke({"query": "解除劳动合同的补偿规则"})

    assert result["legal_authorities"][0]["article_label"] == "第一条"
    assert retrieval.calls == [("legal", "解除劳动合同的补偿规则")]


@pytest.mark.asyncio
async def test_prepare_legal_turn_stages_profile_and_runs_multiple_authority_queries() -> None:
    memory = RecordingCaseMemory()
    retrieval = RecordingRetrieval()
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(
            retrieval,
            memory,
            user_message="公司辞退我能要什么补偿？",
        )
    }

    assert "prepare_legal_turn" in tools

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "解除劳动合同的经济补偿",
            "case_type": "劳动合同解除争议",
            "parties": ["用户（劳动者）", "公司（用人单位）"],
            "key_facts": ["公司已经通知用户解除劳动合同"],
            "authority_queries": ["经济补偿计算标准", "违法解除赔偿金"],
            "decision_factor_keys": [
                "labor.termination.reason",
                "labor.termination.service_years",
            ],
            "factor_updates": [
                {
                    "key": "labor.termination.reason",
                    "label": "解除理由",
                    "type": "text",
                    "state": "unknown",
                    "materiality": "high",
                    "question": "公司或劳动者提出解除的理由是什么？",
                },
                {
                    "key": "labor.termination.service_years",
                    "label": "工作年限",
                    "type": "numeric",
                    "state": "unknown",
                    "materiality": "high",
                    "question": "一共工作了多久？",
                },
            ],
        }
    )

    assert result["case_profile"]["case_type"] == "劳动合同解除争议"
    assert result["case_profile"]["missing_information"] == [
        "公司或劳动者提出解除的理由是什么？",
        "一共工作了多久？",
    ]
    factor_states = {
        factor["key"]: factor["state"]
        for factor in result["case_profile"]["factor_profile"]["factors"]
    }
    assert factor_states == {
        "labor.termination.reason": "unknown",
        "labor.termination.service_years": "unknown",
    }
    assert memory.patches[0].key_facts == ["公司已经通知用户解除劳动合同"]
    assert memory.patches[0].factor_profile is not None
    assert len(memory.patches) == 1
    assert [call for call in retrieval.calls if call[0] == "legal"] == [
        ("legal", "公司辞退我能要什么补偿？"),
        ("legal", "经济补偿计算标准"),
        ("legal", "违法解除赔偿金"),
    ]
    assert len(result["legal_authorities"]) == 3
    assert len(result["turn_preparation"]["authority_query_coverage"]) == 3
    assert result["response_contract"]["follow_up_questions"] == [
        {
            "factor_key": "labor.termination.reason",
            "question": "公司或劳动者提出解除的理由是什么？",
        },
        {
            "factor_key": "labor.termination.service_years",
            "question": "一共工作了多久？",
        },
    ]
    assert result["response_contract"]["maximum_follow_up_questions"] == 2


@pytest.mark.asyncio
async def test_prepare_legal_turn_interleaves_ranked_query_results() -> None:
    retrieval = RankedRetrieval()
    tools = {
        tool.name: tool for tool in build_lexora_tools(retrieval, None, user_message="盗窃约五万元")
    }

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "盗窃罪量刑",
            "authority_queries": ["盗窃数额标准", "累犯成立条件"],
            "decision_factor_keys": ["criminal.theft.prior_conviction"],
            "factor_updates": [
                {
                    "key": "criminal.theft.prior_conviction",
                    "label": "前科及累犯相关情况",
                    "type": "text",
                    "state": "unknown",
                    "materiality": "high",
                    "question": "前罪刑罚何时执行完毕？",
                }
            ],
        }
    )

    references = [item["reference"] for item in result["legal_authorities"]]
    first_rank_references = {
        coverage["references"][0]
        for coverage in result["turn_preparation"]["authority_query_coverage"]
    }

    assert len(references) == 12
    assert first_rank_references <= set(references)


@pytest.mark.asyncio
async def test_prepare_legal_turn_bounds_authority_search_concurrency() -> None:
    class ConcurrencyTrackingRetrieval(RecordingRetrieval):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.maximum_active = 0

        async def search_legal_authorities(self, query: str):
            self.calls.append(("legal", query))
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return ()

    retrieval = ConcurrencyTrackingRetrieval()
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(retrieval, None, user_message="劳动争议")
    }

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "解除劳动合同",
            "authority_queries": ["经济补偿", "违法解除", "举证责任"],
        }
    )

    assert len(result["turn_preparation"]["authority_queries"]) == 4
    assert retrieval.maximum_active == 2


@pytest.mark.asyncio
async def test_prepare_social_turn_skips_retrieval_and_case_updates() -> None:
    memory = RecordingCaseMemory()
    retrieval = RecordingRetrieval()
    tools = {tool.name: tool for tool in build_lexora_tools(retrieval, memory, user_message="hi")}

    result = await tools["prepare_legal_turn"].ainvoke({"intent": "social"})

    assert result["turn_preparation"]["intent"] == "social"
    assert result["legal_authorities"] == []
    assert retrieval.calls == []
    assert memory.patches == []


@pytest.mark.asyncio
async def test_prepare_legal_turn_does_not_reask_denied_relationship_factor() -> None:
    memory = RecordingCaseMemory()
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(
            RecordingRetrieval(),
            memory,
            user_message=(
                "我女朋友结婚了，但已经和她老公分居好几年，是不是算自动离婚了？"
                "我们没以夫妻的名义同居算重婚吗？"
            ),
        )
    }

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "分居是否自动解除婚姻及是否构成重婚",
            "case_type": "婚姻关系状态与关系重叠",
            "key_facts": [
                "女朋友仍处于婚姻关系中并已与其配偶分居多年",
                "用户与女朋友没有以夫妻名义同居",
            ],
            "authority_queries": ["分居是否自动解除婚姻关系", "重婚罪构成要件"],
            "decision_factor_keys": [
                "relationship.holds_out_as_spouses",
                "relationship.second_marriage_registered",
            ],
            "factor_updates": [
                {
                    "key": "relationship.holds_out_as_spouses",
                    "label": "是否以夫妻身份生活",
                    "type": "boolean",
                    "state": "denied",
                    "value": False,
                    "materiality": "high",
                    "question": "你们是否曾对外以夫妻身份生活？",
                },
                {
                    "key": "relationship.second_marriage_registered",
                    "label": "是否再次登记结婚",
                    "type": "boolean",
                    "state": "unknown",
                    "materiality": "high",
                    "question": "你们是否办理过结婚登记？",
                }
            ],
        }
    )

    assert result["case_profile"]["missing_information"] == [
        "你们是否办理过结婚登记？"
    ]
    assert result["response_contract"]["follow_up_questions"] == [
        {
            "factor_key": "relationship.second_marriage_registered",
            "question": "你们是否办理过结婚登记？",
        }
    ]
    held_out_factor = next(
        factor
        for factor in result["case_profile"]["factor_profile"]["factors"]
        if factor["key"] == "relationship.holds_out_as_spouses"
    )
    assert held_out_factor["state"] == "denied"
    assert held_out_factor["value"] is False
