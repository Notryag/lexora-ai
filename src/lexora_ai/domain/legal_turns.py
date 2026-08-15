from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from lexora_ai.domain.factors import FactorMateriality, FactorState, FactorType


class LegalTurnIntent(StrEnum):
    social = "social"
    case_update = "case_update"
    legal_question = "legal_question"


class LegalTurnAnswerMode(StrEnum):
    direct = "direct"
    conditional = "conditional"


class LegalTurnAnswerKind(StrEnum):
    rule = "rule"
    classification = "classification"
    estimate = "estimate"
    calculation = "calculation"
    action = "action"


class LegalTurnFollowUpImpact(StrEnum):
    liability = "liability"
    legal_range = "legal_range"
    amount = "amount"
    next_action = "next_action"


class LegalTurnContextStatus(StrEnum):
    explicit = "explicit"
    entailed = "entailed"
    partially_resolved = "partially_resolved"
    unresolved = "unresolved"


class LegalTurnFactorGroundingStatus(StrEnum):
    grounded = "grounded"
    unsupported = "unsupported"
    overbroad = "overbroad"
    conflicting = "conflicting"


class LegalTurnAnswerTarget(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=300,
        description="One question the user actually asked, without adding a new issue.",
    )
    mode: LegalTurnAnswerMode = Field(
        description=(
            "Use direct when current facts support a bounded answer; use conditional when the "
            "answer must show explicit branches. Neither mode permits withholding the answer."
        )
    )
    kind: LegalTurnAnswerKind = Field(
        description=(
            "Classify the requested deliverable. Rule and classification targets are answered "
            "with bounded branches and do not trigger automatic follow-up questions."
        )
    )

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        return value.strip()


class LegalTurnFollowUpCandidate(BaseModel):
    factor_key: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$",
    )
    answer_target_index: int = Field(ge=0, le=3)
    impact: LegalTurnFollowUpImpact
    reason: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "Explain the concrete change this answer could make to liability, legal range, "
            "amount, or the user's next action."
        ),
    )

    @field_validator("factor_key", "reason")
    @classmethod
    def normalize_candidate_text(cls, value: str) -> str:
        return value.strip()


class LegalTurnFollowUpReview(BaseModel):
    factor_key: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$",
    )
    context_status: LegalTurnContextStatus = Field(
        description=(
            "Classify this candidate against all current user wording and case memory. Explicit, "
            "entailed, or partially_resolved candidates are rejected; only wholly unresolved "
            "atomic candidates may be asked."
        )
    )
    context_basis: str = Field(
        min_length=1,
        max_length=300,
        description=(
            "Identify what the context establishes. Use partially_resolved when any component of "
            "a compound factor is already known. For unresolved, explain why every component and "
            "both material outcomes remain open after considering the question's ordinary premise."
        ),
    )

    @field_validator("factor_key", "context_basis")
    @classmethod
    def normalize_review_text(cls, value: str) -> str:
        return value.strip()


class LegalTurnFactorUpdate(BaseModel):
    key: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$",
        description=(
            "AI-discovered stable semantic key. Reuse an existing case factor key whenever the "
            "same fact dimension already exists."
        ),
    )
    label: str = Field(min_length=1, max_length=120)
    type: FactorType
    state: FactorState
    value: bool | int | float | str | None = None
    materiality: FactorMateriality = FactorMateriality.medium
    question: str | None = Field(
        default=None,
        max_length=300,
        description="Neutral factual question used only when this factor is unknown and material.",
    )

    @field_validator("key", "label", "question", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def validate_unknown_factor(self) -> LegalTurnFactorUpdate:
        if self.state == FactorState.unknown:
            self.value = None
            if not self.question:
                raise ValueError("unknown factors require a follow-up question")
        return self


class LegalTurnFactorGroundingReview(BaseModel):
    factor_key: str = Field(
        min_length=3,
        max_length=120,
        pattern=r"^[a-z][a-z0-9]*(?:[._][a-z0-9]+)*$",
    )
    status: LegalTurnFactorGroundingStatus
    context_basis: str = Field(
        min_length=1,
        max_length=300,
        description="Explain whether the exact factor state and scope follow from user wording.",
    )

    @field_validator("factor_key", "context_basis")
    @classmethod
    def normalize_grounding_text(cls, value: str) -> str:
        return value.strip()


class LegalTurnPreparation(BaseModel):
    intent: LegalTurnIntent
    legal_issue: str | None = Field(default=None, max_length=300)
    case_type: str | None = Field(default=None, max_length=200)
    parties: list[str] = Field(default_factory=list, max_length=10)
    claims: list[str] = Field(default_factory=list, max_length=10)
    key_facts: list[str] = Field(default_factory=list, max_length=16)
    disputed_issues: list[str] = Field(default_factory=list, max_length=8)
    evidence_notes: list[str] = Field(default_factory=list, max_length=8)
    authority_queries: list[str] = Field(default_factory=list, max_length=3)
    material_query: str | None = Field(default=None, max_length=300)
    case_law_query: str | None = Field(default=None, max_length=300)
    answer_targets: list[LegalTurnAnswerTarget] = Field(default_factory=list, max_length=4)
    follow_up_candidates: list[LegalTurnFollowUpCandidate] = Field(
        default_factory=list,
        max_length=4,
    )
    factor_updates: list[LegalTurnFactorUpdate] = Field(default_factory=list, max_length=12)

    @field_validator(
        "legal_issue",
        "case_type",
        "material_query",
        "case_law_query",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator(
        "parties",
        "claims",
        "key_facts",
        "disputed_issues",
        "evidence_notes",
        "authority_queries",
    )
    @classmethod
    def normalize_items(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result

    @model_validator(mode="after")
    def validate_intent_payload(self) -> LegalTurnPreparation:
        if self.intent == LegalTurnIntent.legal_question and not self.legal_issue:
            raise ValueError("legal_question requires legal_issue")
        if self.intent == LegalTurnIntent.legal_question and not self.answer_targets:
            raise ValueError("legal_question requires at least one answer target")
        if self.intent != LegalTurnIntent.legal_question and any(
            (self.answer_targets, self.follow_up_candidates)
        ):
            raise ValueError("only legal_question turns can define answer or follow-up targets")
        candidate_keys = [candidate.factor_key for candidate in self.follow_up_candidates]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("follow-up candidate factor keys must be unique")
        factor_keys = [factor.key for factor in self.factor_updates]
        if len(factor_keys) != len(set(factor_keys)):
            raise ValueError("factor update keys must be unique")
        if any(
            candidate.answer_target_index >= len(self.answer_targets)
            for candidate in self.follow_up_candidates
        ):
            raise ValueError("follow-up candidate references an unknown answer target")
        if self.intent == LegalTurnIntent.social and any(
            (
                self.legal_issue,
                self.authority_queries,
                self.material_query,
                self.case_law_query,
                self.answer_targets,
                self.follow_up_candidates,
                self.factor_updates,
            )
        ):
            raise ValueError("social turns cannot request legal analysis")
        return self
