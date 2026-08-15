from __future__ import annotations

from pydantic import BaseModel, Field

from lexora_ai.domain.factors import CaseFactorProfile, FactorMateriality, FactorState
from lexora_ai.domain.legal_turns import (
    LegalTurnAnswerKind,
    LegalTurnAnswerTarget,
    LegalTurnContextStatus,
    LegalTurnFollowUpCandidate,
    LegalTurnFollowUpImpact,
    LegalTurnFollowUpReview,
    LegalTurnIntent,
)


class FollowUpQuestion(BaseModel):
    factor_key: str | None = Field(default=None, max_length=120)
    question: str = Field(min_length=1, max_length=300)
    impact: LegalTurnFollowUpImpact
    reason: str = Field(min_length=1, max_length=300)


class SufficiencyDecision(BaseModel):
    answer_now: bool = True
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list, max_length=2)


class SufficiencyGate:
    def evaluate(
        self,
        *,
        intent: LegalTurnIntent,
        factor_profile: CaseFactorProfile,
        answer_targets: list[LegalTurnAnswerTarget],
        follow_up_candidates: list[LegalTurnFollowUpCandidate],
        follow_up_reviews: list[LegalTurnFollowUpReview],
    ) -> SufficiencyDecision:
        if intent != LegalTurnIntent.legal_question:
            return SufficiencyDecision(answer_now=True)

        questions: list[FollowUpQuestion] = []
        factors_by_key = {factor.key: factor for factor in factor_profile.factors}
        reviews_by_key = {review.factor_key: review for review in follow_up_reviews}
        seen_factor_keys: set[str] = set()

        for candidate in follow_up_candidates:
            target = answer_targets[candidate.answer_target_index]
            if target.kind not in {
                LegalTurnAnswerKind.estimate,
                LegalTurnAnswerKind.calculation,
                LegalTurnAnswerKind.action,
            }:
                continue
            factor = factors_by_key.get(candidate.factor_key)
            review = reviews_by_key.get(candidate.factor_key)
            if factor is None or factor.key in seen_factor_keys:
                continue
            if review is None or review.context_status != LegalTurnContextStatus.unresolved:
                continue
            if factor.state != FactorState.unknown:
                continue
            if factor.materiality != FactorMateriality.high:
                continue
            if not factor.question:
                continue
            questions.append(
                FollowUpQuestion(
                    factor_key=factor.key,
                    question=factor.question,
                    impact=candidate.impact,
                    reason=candidate.reason,
                )
            )
            seen_factor_keys.add(factor.key)
            if len(questions) == 2:
                break

        return SufficiencyDecision(answer_now=True, follow_up_questions=questions)
