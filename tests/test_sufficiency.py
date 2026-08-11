from __future__ import annotations

from lexora_ai.domain import (
    CaseFactor,
    CaseFactorProfile,
    FactorMateriality,
    FactorState,
    FactorType,
    LegalTurnIntent,
    SufficiencyGate,
)


def test_sufficiency_gate_uses_decision_variables_first() -> None:
    gate = SufficiencyGate()

    decision = gate.evaluate(
        intent=LegalTurnIntent.legal_question,
        factor_profile=CaseFactorProfile(),
        decision_variables=["解除理由", "工作年限", "通知方式"],
    )

    assert [question.question for question in decision.follow_up_questions] == [
        "解除理由",
        "工作年限",
    ]


def test_sufficiency_gate_falls_back_to_unknown_high_materiality_factors() -> None:
    gate = SufficiencyGate()

    decision = gate.evaluate(
        intent=LegalTurnIntent.legal_question,
        factor_profile=CaseFactorProfile(
            factors=[
                CaseFactor(
                    key="labor.termination.reason",
                    label="解除理由",
                    type=FactorType.text,
                    state=FactorState.unknown,
                    materiality=FactorMateriality.high,
                    question="公司或劳动者提出解除的理由是什么？",
                )
            ]
        ),
        decision_variables=[],
    )

    assert decision.follow_up_questions[0].factor_key == "labor.termination.reason"
