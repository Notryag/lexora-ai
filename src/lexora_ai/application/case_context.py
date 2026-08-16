from __future__ import annotations

from lexora_ai.application.ports import ConversationCaseMemoryPort
from lexora_ai.domain import (
    CaseFactorProfile,
    CaseProfile,
    CaseProfilePatch,
    FactorState,
    LegalTurnAssessment,
    LegalTurnContextStatus,
    LegalTurnFollowUpReview,
    LegalTurnIntent,
    LegalTurnPreparation,
    SufficiencyGate,
)


def _profile_for_commit(
    profile: CaseFactorProfile,
    admitted_factor_keys: set[str],
) -> CaseFactorProfile:
    committed = profile.model_copy(deep=True)
    committed.factors = [
        factor
        for factor in committed.factors
        if factor.state != FactorState.unknown or factor.key in admitted_factor_keys
    ]
    return committed


class CaseContextService:
    """Apply a Case Analyst result to application-owned conversation state."""

    def __init__(
        self,
        case_memory: ConversationCaseMemoryPort | None,
        *,
        jurisdiction: str,
    ) -> None:
        self._case_memory = case_memory
        self._jurisdiction = jurisdiction
        self._sufficiency_gate = SufficiencyGate()

    async def process(self, raw_assessment: object) -> dict[str, object]:
        assessment = LegalTurnAssessment.model_validate(raw_assessment)
        current_profile = (
            await self._case_memory.get_profile()
            if self._case_memory is not None
            else CaseProfile()
        )
        resumed_targets = current_profile.pending_answer_targets
        resume_previous_analysis = (
            assessment.intent == LegalTurnIntent.case_update and bool(resumed_targets)
        )
        effective_intent = (
            LegalTurnIntent.legal_question
            if resume_previous_analysis
            else assessment.intent
        )
        effective_targets = assessment.answer_targets or (
            resumed_targets if resume_previous_analysis else []
        )
        effective_issue = assessment.legal_issue or (
            resumed_targets[0].question if resume_previous_analysis else None
        )
        context = LegalTurnPreparation(
            intent=effective_intent,
            legal_issue=effective_issue,
            case_type=assessment.case_type,
            parties=assessment.parties,
            claims=assessment.claims,
            key_facts=assessment.key_facts,
            disputed_issues=assessment.disputed_issues,
            evidence_notes=assessment.evidence_notes,
            answer_targets=effective_targets,
            follow_up_candidates=(
                assessment.follow_up_candidates
                if effective_intent == LegalTurnIntent.legal_question
                else []
            ),
            factor_updates=assessment.factor_updates,
        )

        factor_profile = current_profile.factor_profile.apply_updates(
            context.factor_updates
        )
        reviews = [
            LegalTurnFollowUpReview(
                factor_key=candidate.factor_key,
                context_status=LegalTurnContextStatus.unresolved,
                context_basis=(
                    "Case Analyst marked this atomic factor unresolved after considering the "
                    "current turn and case profile."
                ),
            )
            for candidate in context.follow_up_candidates
        ]
        sufficiency = self._sufficiency_gate.evaluate(
            intent=context.intent,
            factor_profile=factor_profile,
            answer_targets=context.answer_targets,
            follow_up_candidates=context.follow_up_candidates,
            follow_up_reviews=reviews,
        )

        updated_profile: CaseProfile | None = None
        if self._case_memory is not None and context.intent != LegalTurnIntent.social:
            admitted_factor_keys = {
                question.factor_key
                for question in sufficiency.follow_up_questions
                if question.factor_key is not None
            }
            updated_profile = await self._case_memory.update_profile(
                CaseProfilePatch(
                    case_type=context.case_type,
                    parties=context.parties,
                    claims=context.claims,
                    key_facts=context.key_facts,
                    disputed_issues=context.disputed_issues,
                    evidence_notes=context.evidence_notes,
                    missing_information=[
                        question.question for question in sufficiency.follow_up_questions
                    ],
                    pending_answer_targets=context.answer_targets,
                    factor_profile=_profile_for_commit(
                        factor_profile,
                        admitted_factor_keys,
                    ),
                )
            )

        known_factors = [
            factor for factor in factor_profile.factors if factor.state != FactorState.unknown
        ]
        return {
            "assessment": assessment.model_dump(mode="json"),
            "case_context": {
                "intent": context.intent.value,
                "legal_issue": context.legal_issue,
                "user_stated_facts": context.key_facts,
                "answer_targets": [
                    target.model_dump(mode="json") for target in context.answer_targets
                ],
                "factor_updates": [
                    update.model_dump(mode="json") for update in context.factor_updates
                ],
            },
            "case_profile": (
                updated_profile.model_dump(mode="json")
                if updated_profile is not None
                else None
            ),
            "response_contract": {
                "answer_current_question_first": True,
                "jurisdiction": self._jurisdiction,
                "jurisdiction_confirmation_required": False,
                "answer_targets": [
                    target.model_dump(mode="json") for target in context.answer_targets
                ],
                "maximum_follow_up_questions": len(sufficiency.follow_up_questions),
                "exact_outcome_prediction_allowed": False,
                "separate_known_facts_from_conditions": True,
                "do_not_reask_known_facts": True,
                "do_not_introduce_hypotheticals_contrary_to_known_facts": True,
                "known_factor_constraints": [
                    {
                        "key": factor.key,
                        "label": factor.label,
                        "state": factor.state.value,
                        "value": factor.value,
                    }
                    for factor in known_factors
                ],
                "prohibited_counterfactual_factor_keys": [
                    factor.key
                    for factor in known_factors
                    if factor.state == FactorState.denied or factor.value is False
                ],
                "follow_up_questions": [
                    question.model_dump(mode="json")
                    for question in sufficiency.follow_up_questions
                ],
            },
        }
