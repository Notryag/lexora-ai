from __future__ import annotations

import asyncio

import pytest

from lexora_ai.application import ConversationLegalChunk
from lexora_ai.domain import (
    CaseProfile,
    LegalTurnAnswerTarget,
    LegalTurnFactorGroundingReview,
    LegalTurnFactorUpdate,
    LegalTurnFollowUpReview,
    LegalTurnPreparation,
)
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
    def __init__(self, *, pending_answer_targets=None) -> None:
        self.profile = CaseProfile(missing_information=["房屋购买时间"])
        if pending_answer_targets is not None:
            self.profile.pending_answer_targets = pending_answer_targets
        self.patches = []

    async def get_profile(self):
        return self.profile.model_copy(deep=True)

    async def update_profile(self, patch):
        self.patches.append(patch)
        self.profile = patch.apply(self.profile)
        return self.profile


class StaticReviewer:
    def __init__(self, reviews: list[dict[str, object]]) -> None:
        self.reviews = [LegalTurnFollowUpReview.model_validate(review) for review in reviews]

    async def review(self, **_kwargs):
        return self.reviews


class StaticFactorReviewer:
    def __init__(self, reviews: list[dict[str, object]]) -> None:
        self.reviews = [
            LegalTurnFactorGroundingReview.model_validate(review) for review in reviews
        ]

    async def review_factor_updates(self, **_kwargs):
        return self.reviews


def test_factor_generation_rules_live_in_the_input_schema() -> None:
    factor_fields = LegalTurnFactorUpdate.model_fields
    preparation_fields = LegalTurnPreparation.model_fields

    assert "Reuse the exact existing case_profile key" in (
        factor_fields["key"].description or ""
    )
    assert "explicitly negated fact" in (
        factor_fields["state"].description or ""
    )
    assert "approximate wording" in (factor_fields["value"].description or "")
    assert "Never include legal rules" in (
        preparation_fields["factor_updates"].description or ""
    )
    assert "Application review decides" in (
        preparation_fields["follow_up_candidates"].description or ""
    )


@pytest.mark.asyncio
async def test_agent_retrieval_tools_keep_sources_separate() -> None:
    retrieval = RecordingRetrieval()
    tools = {
        tool.name: tool for tool in build_lexora_tools(retrieval, None, user_message="解除劳动合同")
    }

    assert set(tools) == {
        "prepare_legal_turn",
        "calculate_employment_termination_compensation",
        "search_case_materials",
        "search_legal_authorities",
        "search_guiding_cases",
    }
    assert len(tools["prepare_legal_turn"].description.split()) <= 100

    result = await tools["search_legal_authorities"].ainvoke({"query": "解除劳动合同的补偿规则"})

    assert result["legal_authorities"][0]["article_label"] == "第一条"
    assert retrieval.calls == [("legal", "解除劳动合同的补偿规则")]


@pytest.mark.asyncio
async def test_case_update_resumes_pending_analysis_and_retrieves_authorities() -> None:
    target = LegalTurnAnswerTarget(
        question="补充金额后大概会判多久？",
        mode="conditional",
        kind="estimate",
    )
    memory = RecordingCaseMemory(pending_answer_targets=[target])
    retrieval = RecordingRetrieval()
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(
            retrieval,
            memory,
            user_message="补充：涉案金额约5万元，已认罪认罚。",
        )
    }

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "case_update",
            "key_facts": ["涉案金额约5万元", "已认罪认罚"],
        }
    )

    assert result["turn_preparation"]["intent"] == "legal_question"
    assert result["response_contract"]["answer_targets"] == [
        {
            "question": "补充金额后大概会判多久？",
            "mode": "conditional",
            "kind": "estimate",
        }
    ]
    assert result["legal_authorities"]
    assert any(kind == "legal" for kind, _ in retrieval.calls)


def test_employment_compensation_tool_returns_exact_n_and_2n() -> None:
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(None, None, user_message="公司辞退如何计算赔偿")
    }

    result = tools["calculate_employment_termination_compensation"].invoke(
        {
            "completed_years": 3,
            "additional_months": 2,
            "monthly_wage": "10000",
        }
    )

    assert result["compensation_months"] == "3.50"
    assert result["economic_compensation_n"] == "35000.00"
    assert result["unlawful_termination_damages_2n"] == "70000.00"


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
            follow_up_reviewer=StaticReviewer(
                [
                    {
                        "factor_key": "labor.termination.reason",
                        "context_status": "unresolved",
                        "context_basis": "用户没有说明公司提出的解除理由。",
                    },
                    {
                        "factor_key": "labor.termination.service_years",
                        "context_status": "unresolved",
                        "context_basis": "用户没有说明工作年限。",
                    },
                ]
            ),
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
            "answer_targets": [
                {
                    "question": "公司辞退后可以主张什么补偿？",
                    "mode": "conditional",
                    "kind": "calculation",
                }
            ],
            "follow_up_candidates": [
                {
                    "factor_key": "labor.termination.reason",
                    "answer_target_index": 0,
                    "impact": "liability",
                    "reason": "解除理由会影响经济补偿或违法解除赔偿责任。",
                },
                {
                    "factor_key": "labor.termination.service_years",
                    "answer_target_index": 0,
                    "impact": "amount",
                    "reason": "工作年限会改变经济补偿的计算金额。",
                },
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
            "impact": "liability",
            "reason": "解除理由会影响经济补偿或违法解除赔偿责任。",
        },
        {
            "factor_key": "labor.termination.service_years",
            "question": "一共工作了多久？",
            "impact": "amount",
            "reason": "工作年限会改变经济补偿的计算金额。",
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
            "answer_targets": [
                {
                    "question": "入户盗窃约五万元大概会判多久？",
                    "mode": "conditional",
                    "kind": "estimate",
                }
            ],
            "follow_up_candidates": [
                {
                    "factor_key": "criminal.theft.prior_conviction",
                    "answer_target_index": 0,
                    "impact": "legal_range",
                    "reason": "前罪执行完毕时间可能影响是否构成累犯及从重幅度。",
                }
            ],
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

    preparation_result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "解除劳动合同",
            "answer_targets": [
                {
                    "question": "解除劳动合同后可以主张什么？",
                    "mode": "conditional",
                    "kind": "action",
                }
            ],
            "authority_queries": ["经济补偿", "违法解除", "举证责任"],
        }
    )

    assert len(preparation_result["turn_preparation"]["authority_queries"]) == 4
    assert preparation_result["response_contract"]["jurisdiction"] == "中国大陆"
    assert preparation_result["response_contract"]["jurisdiction_confirmation_required"] is False
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
            follow_up_reviewer=StaticReviewer(
                [
                    {
                        "factor_key": "relationship.holds_out_as_spouses",
                        "context_status": "explicit",
                        "context_basis": "用户明确称双方没有以夫妻名义同居。",
                    },
                    {
                        "factor_key": "relationship.second_marriage_registered",
                        "context_status": "entailed",
                        "context_basis": "用户将对方称为女朋友，并否认以夫妻名义共同生活。",
                    },
                ]
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
            "answer_targets": [
                {
                    "question": "分居多年是否会自动离婚？",
                    "mode": "direct",
                    "kind": "rule",
                },
                {
                    "question": "没有以夫妻名义同居是否构成重婚？",
                    "mode": "conditional",
                    "kind": "classification",
                },
            ],
            "follow_up_candidates": [
                {
                    "factor_key": "relationship.holds_out_as_spouses",
                    "answer_target_index": 1,
                    "impact": "liability",
                    "reason": "是否以夫妻身份生活会影响重婚评价。",
                },
                {
                    "factor_key": "relationship.second_marriage_registered",
                    "answer_target_index": 1,
                    "impact": "liability",
                    "reason": "是否再次登记结婚会影响重婚评价。",
                },
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

    assert result["case_profile"]["missing_information"] == []
    assert result["response_contract"]["follow_up_questions"] == []
    assert result["response_contract"]["prohibited_counterfactual_factor_keys"] == [
        "relationship.holds_out_as_spouses"
    ]
    assert result["response_contract"]["answer_targets"] == [
        {"question": "分居多年是否会自动离婚？", "mode": "direct", "kind": "rule"},
        {
            "question": "没有以夫妻名义同居是否构成重婚？",
            "mode": "conditional",
            "kind": "classification",
        },
    ]
    held_out_factor = next(
        factor
        for factor in result["case_profile"]["factor_profile"]["factors"]
        if factor["key"] == "relationship.holds_out_as_spouses"
    )
    assert held_out_factor["state"] == "denied"
    assert held_out_factor["value"] is False
    assert {
        factor["key"] for factor in result["case_profile"]["factor_profile"]["factors"]
    } == {"relationship.holds_out_as_spouses"}


@pytest.mark.asyncio
async def test_prepare_legal_turn_drops_an_overbroad_claimed_factor() -> None:
    memory = RecordingCaseMemory()
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(
            RecordingRetrieval(),
            memory,
            user_message="我们没有以夫妻名义同居。",
            factor_update_reviewer=StaticFactorReviewer(
                [
                    {
                        "factor_key": "relationship.holds_out_as_spouses",
                        "status": "grounded",
                        "context_basis": "用户原话直接否定以夫妻身份生活。",
                    },
                    {
                        "factor_key": "cohabitation.present",
                        "status": "overbroad",
                        "context_basis": "原话没有否定共同居住本身。",
                    },
                ]
            ),
        )
    }

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "是否构成重婚",
            "answer_targets": [
                {
                    "question": "没有以夫妻名义同居是否构成重婚？",
                    "mode": "direct",
                    "kind": "classification",
                }
            ],
            "key_facts": ["用户称双方没有以夫妻名义同居"],
            "factor_updates": [
                {
                    "key": "relationship.holds_out_as_spouses",
                    "label": "是否以夫妻身份生活",
                    "type": "boolean",
                    "state": "denied",
                    "value": False,
                    "materiality": "high",
                },
                {
                    "key": "cohabitation.present",
                    "label": "是否共同生活",
                    "type": "boolean",
                    "state": "denied",
                    "value": False,
                    "materiality": "high",
                },
            ],
        }
    )

    assert [
        factor["key"] for factor in result["case_profile"]["factor_profile"]["factors"]
    ] == ["relationship.holds_out_as_spouses"]
    assert [
        factor["key"] for factor in result["turn_preparation"]["factor_updates"]
    ] == ["relationship.holds_out_as_spouses"]
    assert result["turn_preparation"]["factor_grounding_review"][1]["status"] == (
        "overbroad"
    )


@pytest.mark.asyncio
async def test_prepare_legal_turn_asks_only_unresolved_theft_factor() -> None:
    memory = RecordingCaseMemory()
    tools = {
        tool.name: tool
        for tool in build_lexora_tools(
            RecordingRetrieval(),
            memory,
            user_message=(
                "这次偷的东西价值大概五万元，没有退赃，没带凶器，是一个人干的，"
                "到法庭后认罪认罚了。"
            ),
            follow_up_reviewer=StaticReviewer(
                [
                    {
                        "factor_key": "criminal.theft.amount",
                        "context_status": "explicit",
                        "context_basis": "用户明确说明价值约五万元。",
                    },
                    {
                        "factor_key": "criminal.theft.weapon_carried",
                        "context_status": "explicit",
                        "context_basis": "用户明确说明没有携带凶器。",
                    },
                    {
                        "factor_key": "criminal.theft.guilty_plea",
                        "context_status": "explicit",
                        "context_basis": "用户明确说明已经认罪认罚。",
                    },
                    {
                        "factor_key": "criminal.prior_sentence_completion",
                        "context_status": "unresolved",
                        "context_basis": "用户没有说明前次刑罚执行完毕时间。",
                    },
                ]
            ),
        )
    }

    result = await tools["prepare_legal_turn"].ainvoke(
        {
            "intent": "legal_question",
            "legal_issue": "入户盗窃的量刑区间",
            "answer_targets": [
                {
                    "question": "根据补充事实大概会判多久？",
                    "mode": "conditional",
                    "kind": "estimate",
                }
            ],
            "key_facts": [
                "盗窃财物价值约五万元",
                "未退赃",
                "未携带凶器",
                "单独作案",
                "已认罪认罚",
            ],
            "follow_up_candidates": [
                {
                    "factor_key": "criminal.theft.amount",
                    "answer_target_index": 0,
                    "impact": "legal_range",
                    "reason": "盗窃金额会影响法定量刑档次。",
                },
                {
                    "factor_key": "criminal.theft.weapon_carried",
                    "answer_target_index": 0,
                    "impact": "legal_range",
                    "reason": "携带凶器可能影响行为评价。",
                },
                {
                    "factor_key": "criminal.theft.guilty_plea",
                    "answer_target_index": 0,
                    "impact": "legal_range",
                    "reason": "认罪认罚可能影响从宽幅度。",
                },
                {
                    "factor_key": "criminal.prior_sentence_completion",
                    "answer_target_index": 0,
                    "impact": "legal_range",
                    "reason": "前罪执行完毕时间可能影响是否构成累犯。",
                },
            ],
            "factor_updates": [
                {
                    "key": "criminal.theft.amount",
                    "label": "盗窃金额",
                    "type": "numeric",
                    "state": "asserted",
                    "value": 50000,
                    "materiality": "high",
                },
                {
                    "key": "criminal.theft.weapon_carried",
                    "label": "是否携带凶器",
                    "type": "boolean",
                    "state": "denied",
                    "value": False,
                    "materiality": "high",
                },
                {
                    "key": "criminal.theft.guilty_plea",
                    "label": "是否认罪认罚",
                    "type": "boolean",
                    "state": "asserted",
                    "value": True,
                    "materiality": "high",
                },
                {
                    "key": "criminal.prior_sentence_completion",
                    "label": "前罪刑罚执行完毕时间",
                    "type": "text",
                    "state": "unknown",
                    "materiality": "high",
                    "question": "前次刑罚何时执行完毕？",
                },
            ],
        }
    )

    assert result["case_profile"]["missing_information"] == ["前次刑罚何时执行完毕？"]
    assert result["response_contract"]["follow_up_questions"] == [
        {
            "factor_key": "criminal.prior_sentence_completion",
            "question": "前次刑罚何时执行完毕？",
            "impact": "legal_range",
            "reason": "前罪执行完毕时间可能影响是否构成累犯。",
        }
    ]
