from __future__ import annotations

from lexora_ai.domain import (
    CaseFactor,
    CaseFactorProfile,
    FactorState,
    FactorType,
    LegalTurnIntent,
    SufficiencyGate,
)


def test_sufficiency_gate_resolves_registered_decision_factor_keys() -> None:
    gate = SufficiencyGate()

    decision = gate.evaluate(
        intent=LegalTurnIntent.legal_question,
        factor_profile=CaseFactorProfile(
            factors=[
                CaseFactor(
                    key="labor.termination.reason",
                    label="解除理由",
                    type=FactorType.text,
                    question="公司为什么解除劳动合同？",
                ),
                CaseFactor(
                    key="labor.termination.service_years",
                    label="工作年限",
                    type=FactorType.numeric,
                    question="你在公司工作了多久？",
                ),
            ]
        ),
        decision_factor_keys=[
            "labor.termination.reason",
            "labor.termination.service_years",
        ],
    )

    assert [question.question for question in decision.follow_up_questions] == [
        "公司为什么解除劳动合同？",
        "你在公司工作了多久？",
    ]


def test_sufficiency_gate_filters_known_and_unregistered_factors() -> None:
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
                )
            ]
        ),
        decision_factor_keys=["labor.termination.reason", "unregistered.factor"],
    )

    assert decision.follow_up_questions == []
