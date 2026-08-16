from __future__ import annotations

from lexora_ai.application import CaseContextService
from lexora_ai.domain import CaseProfile, LegalTurnAnswerTarget


class RecordingCaseMemory:
    def __init__(self, *, pending_answer_targets=None) -> None:
        self.profile = CaseProfile(missing_information=["旧问题"])
        if pending_answer_targets is not None:
            self.profile.pending_answer_targets = pending_answer_targets
        self.patches = []

    async def get_profile(self):
        return self.profile.model_copy(deep=True)

    async def update_profile(self, patch):
        self.patches.append(patch)
        self.profile = patch.apply(self.profile)
        return self.profile


async def test_case_update_resumes_pending_answer_target() -> None:
    target = LegalTurnAnswerTarget(
        question="补充金额后大概会判多久？",
        mode="conditional",
        kind="estimate",
    )
    memory = RecordingCaseMemory(pending_answer_targets=[target])

    result = await CaseContextService(memory, jurisdiction="中国大陆").process(
        {
            "intent": "case_update",
            "key_facts": ["涉案金额约5万元", "已认罪认罚"],
            "factor_updates": [
                {
                    "key": "criminal.theft.amount",
                    "label": "盗窃金额",
                    "type": "text",
                    "state": "asserted",
                    "value": "约5万元",
                    "materiality": "high",
                }
            ],
        }
    )

    assert result["case_context"]["intent"] == "legal_question"
    assert result["response_contract"]["answer_targets"] == [
        target.model_dump(mode="json")
    ]
    assert result["case_profile"]["key_facts"] == ["涉案金额约5万元", "已认罪认罚"]


async def test_classification_target_keeps_denial_without_follow_up() -> None:
    memory = RecordingCaseMemory()

    result = await CaseContextService(memory, jurisdiction="中国大陆").process(
        {
            "intent": "legal_question",
            "legal_issue": "是否构成重婚",
            "key_facts": ["没有以夫妻名义同居"],
            "answer_targets": [
                {
                    "question": "没有以夫妻名义同居是否构成重婚？",
                    "mode": "direct",
                    "kind": "classification",
                }
            ],
            "factor_updates": [
                {
                    "key": "relationship.holds_out_as_spouses",
                    "label": "是否以夫妻身份生活",
                    "type": "boolean",
                    "state": "denied",
                    "value": False,
                    "materiality": "high",
                }
            ],
        }
    )

    contract = result["response_contract"]
    assert contract["follow_up_questions"] == []
    assert contract["prohibited_counterfactual_factor_keys"] == [
        "relationship.holds_out_as_spouses"
    ]
    assert result["case_profile"]["factor_profile"]["factors"][0]["state"] == "denied"


async def test_estimate_target_admits_at_most_two_high_impact_unknowns() -> None:
    memory = RecordingCaseMemory()
    unknowns = [
        ("criminal.prior_completion", "前罪何时执行完毕？", "legal_range"),
        ("criminal.restitution", "是否已经退赃退赔？", "legal_range"),
        ("criminal.address", "详细住址是什么？", "next_action"),
    ]

    result = await CaseContextService(memory, jurisdiction="中国大陆").process(
        {
            "intent": "legal_question",
            "legal_issue": "盗窃罪量刑",
            "answer_targets": [
                {
                    "question": "大概会判多久？",
                    "mode": "conditional",
                    "kind": "estimate",
                }
            ],
            "factor_updates": [
                {
                    "key": key,
                    "label": key,
                    "type": "text",
                    "state": "unknown",
                    "materiality": "high",
                    "question": question,
                }
                for key, question, _impact in unknowns
            ],
            "follow_up_candidates": [
                {
                    "factor_key": key,
                    "answer_target_index": 0,
                    "impact": impact,
                    "reason": "该事实可能改变当前估算。",
                }
                for key, _question, impact in unknowns
            ],
        }
    )

    questions = result["response_contract"]["follow_up_questions"]
    assert [item["factor_key"] for item in questions] == [
        "criminal.prior_completion",
        "criminal.restitution",
    ]
    assert len(result["case_profile"]["factor_profile"]["factors"]) == 2


async def test_social_assessment_does_not_update_case_profile() -> None:
    memory = RecordingCaseMemory()

    result = await CaseContextService(memory, jurisdiction="中国大陆").process(
        {"intent": "social"}
    )

    assert result["case_context"]["intent"] == "social"
    assert result["case_profile"] is None
    assert memory.patches == []
