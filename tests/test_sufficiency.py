from __future__ import annotations

from lexora_ai.domain import (
    CaseFactor,
    CaseFactorProfile,
    FactorMateriality,
    FactorState,
    FactorType,
    LegalTurnAnswerKind,
    LegalTurnAnswerMode,
    LegalTurnAnswerTarget,
    LegalTurnContextStatus,
    LegalTurnFollowUpCandidate,
    LegalTurnFollowUpImpact,
    LegalTurnFollowUpReview,
    LegalTurnIntent,
    SufficiencyGate,
)


def test_sufficiency_gate_admits_high_impact_unknown_candidates() -> None:
    gate = SufficiencyGate()

    decision = gate.evaluate(
        intent=LegalTurnIntent.legal_question,
        factor_profile=CaseFactorProfile(
            factors=[
                CaseFactor(
                    key="labor.termination.reason",
                    label="解除理由",
                    type=FactorType.text,
                    materiality=FactorMateriality.high,
                    question="公司为什么解除劳动合同？",
                ),
                CaseFactor(
                    key="labor.termination.service_years",
                    label="工作年限",
                    type=FactorType.numeric,
                    materiality=FactorMateriality.high,
                    question="你在公司工作了多久？",
                ),
            ]
        ),
        answer_targets=[
            LegalTurnAnswerTarget(
                question="公司辞退后可以主张多少补偿？",
                mode=LegalTurnAnswerMode.conditional,
                kind=LegalTurnAnswerKind.calculation,
            )
        ],
        follow_up_candidates=[
            LegalTurnFollowUpCandidate(
                factor_key="labor.termination.reason",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.liability,
                reason="解除理由会影响是否存在违法解除责任。",
            ),
            LegalTurnFollowUpCandidate(
                factor_key="labor.termination.service_years",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.amount,
                reason="工作年限会改变经济补偿的计算金额。",
            ),
        ],
        follow_up_reviews=[
            LegalTurnFollowUpReview(
                factor_key="labor.termination.reason",
                context_status=LegalTurnContextStatus.unresolved,
                context_basis="用户只说明公司解除合同，没有说明解除理由。",
            ),
            LegalTurnFollowUpReview(
                factor_key="labor.termination.service_years",
                context_status=LegalTurnContextStatus.unresolved,
                context_basis="用户没有说明工作年限。",
            ),
        ],
    )

    assert [question.question for question in decision.follow_up_questions] == [
        "公司为什么解除劳动合同？",
        "你在公司工作了多久？",
    ]


def test_sufficiency_gate_filters_known_unregistered_and_non_high_factors() -> None:
    gate = SufficiencyGate()

    decision = gate.evaluate(
        intent=LegalTurnIntent.legal_question,
        factor_profile=CaseFactorProfile(
            factors=[
                CaseFactor(
                    key="labor.termination.reason",
                    label="解除理由",
                    type=FactorType.text,
                    state=FactorState.denied,
                    value=False,
                    question="公司或劳动者提出解除的理由是什么？",
                ),
                CaseFactor(
                    key="labor.termination.notice_form",
                    label="通知形式",
                    type=FactorType.text,
                    state=FactorState.unknown,
                    materiality=FactorMateriality.medium,
                    question="公司通过什么方式通知？",
                ),
            ]
        ),
        answer_targets=[
            LegalTurnAnswerTarget(
                question="解除后下一步怎么办？",
                mode=LegalTurnAnswerMode.conditional,
                kind=LegalTurnAnswerKind.action,
            )
        ],
        follow_up_candidates=[
            LegalTurnFollowUpCandidate(
                factor_key="labor.termination.reason",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.liability,
                reason="解除理由可能影响责任。",
            ),
            LegalTurnFollowUpCandidate(
                factor_key="unregistered.factor",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.next_action,
                reason="未注册的因素不能进入追问。",
            ),
            LegalTurnFollowUpCandidate(
                factor_key="labor.termination.notice_form",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.next_action,
                reason="通知形式只影响后续取证安排。",
            ),
        ],
        follow_up_reviews=[
            LegalTurnFollowUpReview(
                factor_key="labor.termination.reason",
                context_status=LegalTurnContextStatus.explicit,
                context_basis="该因素已经在案件画像中明确。",
            ),
            LegalTurnFollowUpReview(
                factor_key="unregistered.factor",
                context_status=LegalTurnContextStatus.unresolved,
                context_basis="上下文没有涉及该因素。",
            ),
            LegalTurnFollowUpReview(
                factor_key="labor.termination.notice_form",
                context_status=LegalTurnContextStatus.unresolved,
                context_basis="上下文没有说明通知形式。",
            ),
        ],
    )

    assert decision.follow_up_questions == []


def test_sufficiency_gate_filters_turn_local_entailed_resolution() -> None:
    gate = SufficiencyGate()

    decision = gate.evaluate(
        intent=LegalTurnIntent.legal_question,
        factor_profile=CaseFactorProfile(
            factors=[
                CaseFactor(
                    key="marriage.existing_relationship_terminated",
                    label="现有婚姻是否已依法解除",
                    type=FactorType.boolean,
                    state=FactorState.unknown,
                    materiality=FactorMateriality.high,
                    question="她是否已经办理离婚登记或取得生效离婚裁判？",
                )
            ]
        ),
        answer_targets=[
            LegalTurnAnswerTarget(
                question="分居多年是否自动离婚？",
                mode=LegalTurnAnswerMode.direct,
                kind=LegalTurnAnswerKind.classification,
            )
        ],
        follow_up_candidates=[
            LegalTurnFollowUpCandidate(
                factor_key="marriage.existing_relationship_terminated",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.liability,
                reason="婚姻状态会影响关系重叠的法律评价。",
            )
        ],
        follow_up_reviews=[
            LegalTurnFollowUpReview(
                factor_key="marriage.existing_relationship_terminated",
                context_status=LegalTurnContextStatus.entailed,
                context_basis="用户称对方仍已婚，并询问分居是否会自动离婚。",
            )
        ],
    )

    assert decision.follow_up_questions == []
