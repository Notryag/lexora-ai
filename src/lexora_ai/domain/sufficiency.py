from __future__ import annotations

from pydantic import BaseModel, Field

from lexora_ai.domain.factors import CaseFactorProfile, FactorState
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
        decision_factor_keys: list[str],
    ) -> SufficiencyDecision:
        if intent != LegalTurnIntent.legal_question:
            return SufficiencyDecision(answer_now=True)

        questions: list[FollowUpQuestion] = []
        factors_by_key = {factor.key: factor for factor in factor_profile.factors}
        seen_factor_keys: set[str] = set()

        for key in decision_factor_keys:
            factor = factors_by_key.get(key.strip())
            if factor is None or factor.key in seen_factor_keys:
                continue
            if factor.state != FactorState.unknown:
                continue
            if not factor.question:
                continue
            questions.append(
                FollowUpQuestion(
                    factor_key=factor.key,
                    question=factor.question,
                )
            )
            seen_factor_keys.add(factor.key)
            if len(questions) == 2:
                break

        return SufficiencyDecision(answer_now=True, follow_up_questions=questions)
