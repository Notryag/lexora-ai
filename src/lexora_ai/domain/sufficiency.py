from __future__ import annotations

from pydantic import BaseModel, Field

from lexora_ai.domain.factors import CaseFactorProfile, FactorMateriality, FactorState
from lexora_ai.domain.legal_turns import LegalTurnIntent


class FollowUpQuestion(BaseModel):
    factor_key: str | None = Field(default=None, max_length=120)
    question: str = Field(min_length=1, max_length=300)


class SufficiencyDecision(BaseModel):
    answer_now: bool = True
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list, max_length=2)


class SufficiencyGate:
    def evaluate(
        self,
        *,
        intent: LegalTurnIntent,
        factor_profile: CaseFactorProfile,
        decision_variables: list[str],
    ) -> SufficiencyDecision:
        if intent != LegalTurnIntent.legal_question:
            return SufficiencyDecision(answer_now=True)

        questions: list[FollowUpQuestion] = []
        seen_questions: set[str] = set()

        for variable in decision_variables:
            text = variable.strip()
            if text and text not in seen_questions:
                questions.append(FollowUpQuestion(question=text))
                seen_questions.add(text)
            if len(questions) == 2:
                return SufficiencyDecision(answer_now=True, follow_up_questions=questions)

        for factor in factor_profile.factors:
            if factor.state != FactorState.unknown:
                continue
            if factor.materiality != FactorMateriality.high:
                continue
            if not factor.question or factor.question in seen_questions:
                continue
            questions.append(
                FollowUpQuestion(
                    factor_key=factor.key,
                    question=factor.question,
                )
            )
            seen_questions.add(factor.question)
            if len(questions) == 2:
                break

        return SufficiencyDecision(answer_now=True, follow_up_questions=questions)
