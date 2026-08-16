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


class LegalResearchCoverage(StrEnum):
    sufficient = "sufficient"
    partial = "partial"
    insufficient = "insufficient"


class LegalResearchFinding(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=300,
        description="One research question from the prepared turn.",
    )
    conclusion: str = Field(
        min_length=1,
        max_length=1200,
        description=(
            "Concise rule or comparison supported by the cited search results. Preserve legal "
            "modality and do not turn a case comparison into a prediction."
        ),
    )
    references: list[str] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Only exact L...:C... or C...:S... references returned by research tools that "
            "directly support this finding."
        ),
    )
    limitations: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="Material source, coverage, or applicability limits for this finding.",
    )

    @field_validator("question", "conclusion")
    @classmethod
    def normalize_research_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("references")
    @classmethod
    def validate_references(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for reference in value:
            normalized = reference.strip()
            if not (
                normalized.startswith("L") and ":C" in normalized
                or normalized.startswith("C") and ":S" in normalized
            ):
                raise ValueError("research references must use a legal or case-law reference")
            if normalized not in result:
                result.append(normalized)
        return result

    @field_validator("limitations")
    @classmethod
    def normalize_limitations(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = item.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class LegalResearchDossier(BaseModel):
    coverage: LegalResearchCoverage = Field(
        description=(
            "Whether retrieved sources sufficiently cover every prepared research question."
        )
    )
    findings: list[LegalResearchFinding] = Field(
        default_factory=list,
        max_length=8,
        description="Source-grounded rules and case comparisons for Supervisor synthesis.",
    )
    queries_used: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Exact search queries actually submitted to the research tools.",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        max_length=6,
        description=(
            "Prepared legal research questions not reliably answered by retrieved sources. These "
            "are source-coverage gaps, never requests for more user facts and never permission to "
            "reopen known factors or ordinary premises of the answer target."
        ),
    )

    @field_validator("queries_used", "unresolved_questions")
    @classmethod
    def normalize_research_items(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = item.strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    @model_validator(mode="after")
    def validate_coverage(self) -> LegalResearchDossier:
        if self.coverage == LegalResearchCoverage.sufficient and self.unresolved_questions:
            raise ValueError("sufficient research cannot contain unresolved questions")
        if self.coverage == LegalResearchCoverage.insufficient and self.findings:
            raise ValueError("insufficient research cannot claim supported findings")
        return self


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
        description="Exact key of one unknown factor proposed in factor_updates.",
    )
    answer_target_index: int = Field(
        ge=0,
        le=3,
        description="Zero-based index of the answer target whose outcome this fact can change.",
    )
    impact: LegalTurnFollowUpImpact = Field(
        description="The concrete result dimension that could change if this fact were known.",
    )
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
            "Stable semantic key for one factual dimension. Reuse the exact existing case_profile "
            "key for the same dimension."
        ),
    )
    label: str = Field(
        min_length=1,
        max_length=120,
        description="Neutral label for exactly one fact; do not combine wider conditions.",
    )
    type: FactorType = Field(description="Value type of this single factual dimension.")
    state: FactorState = Field(
        description=(
            "Use asserted for an explicitly affirmed fact, denied for an explicitly negated fact, "
            "unknown only when the fact materially affects the current answer, and conflicting "
            "only when the current statement contradicts stored case facts."
        )
    )
    value: bool | int | float | str | None = Field(
        default=None,
        description=(
            "Only the fact explicitly stated by the user. Preserve qualifiers, negation scope, "
            "and approximate wording; use a string such as '约5万元' instead of false precision."
        ),
    )
    materiality: FactorMateriality = Field(
        default=FactorMateriality.medium,
        description="How strongly this fact can change a current answer target.",
    )
    question: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Neutral question about this fact alone. Required only for an unknown material factor; "
            "do not ask for asserted, denied, or conflicting facts."
        ),
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
        elif self.type == FactorType.boolean and isinstance(self.value, bool):
            if self.value is False and self.state == FactorState.asserted:
                self.state = FactorState.denied
            elif self.value is True and self.state == FactorState.denied:
                self.state = FactorState.conflicting
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


class LegalTurnAssessment(BaseModel):
    """Case Analyst output before research planning or business-memory updates."""

    intent: LegalTurnIntent = Field(
        description=(
            "Classify as social, factual case_update, or legal_question. A factual supplement "
            "without a new question is case_update."
        )
    )
    legal_issue: str | None = Field(
        default=None,
        max_length=300,
        description="Single legal issue raised by a legal question; omit for other intents.",
    )
    case_type: str | None = Field(
        default=None,
        max_length=200,
        description="Concise matter type supported by the user's wording; omit when unclear.",
    )
    parties: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Parties and roles explicitly identified by the user.",
    )
    claims: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Relief, outcome, or action explicitly sought by the user.",
    )
    key_facts: list[str] = Field(
        default_factory=list,
        max_length=16,
        description=(
            "Every concise fact explicitly supplied in the current user turn. Preserve "
            "uncertainty, negation scope, and qualifiers."
        ),
    )
    disputed_issues: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Disputes expressly raised by the user; do not infer additional disputes.",
    )
    evidence_notes: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Evidence the user says exists or can be obtained; never infer evidence.",
    )
    answer_targets: list[LegalTurnAnswerTarget] = Field(
        default_factory=list,
        max_length=4,
        description="Every question the user actually asks, without adding issues.",
    )
    factor_updates: list[LegalTurnFactorUpdate] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Small set of current-turn case facts. Never include legal rules, offenses, "
            "liability, predictions, research queries, or generic warnings."
        ),
    )
    follow_up_candidates: list[LegalTurnFollowUpCandidate] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Only unresolved atomic factors that can change an estimate, calculation, or action "
            "target. Do not propose a candidate for a rule/classification target, a known fact, "
            "or an ordinary premise of the user's question."
        ),
    )

    @field_validator("legal_issue", "case_type", mode="before")
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
    def validate_intent_payload(self) -> LegalTurnAssessment:
        if self.intent == LegalTurnIntent.legal_question and not self.legal_issue:
            raise ValueError("legal_question requires legal_issue")
        if self.intent == LegalTurnIntent.legal_question and not self.answer_targets:
            raise ValueError("legal_question requires at least one answer target")
        if self.intent != LegalTurnIntent.legal_question and self.answer_targets:
            raise ValueError("only legal_question turns can define answer targets")
        factor_keys = [factor.key for factor in self.factor_updates]
        if len(factor_keys) != len(set(factor_keys)):
            raise ValueError("factor update keys must be unique")
        candidate_keys = [candidate.factor_key for candidate in self.follow_up_candidates]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise ValueError("follow-up candidate factor keys must be unique")
        if any(
            candidate.answer_target_index >= len(self.answer_targets)
            for candidate in self.follow_up_candidates
        ):
            raise ValueError("follow-up candidate references an unknown answer target")
        factor_key_set = set(factor_keys)
        if any(candidate.factor_key not in factor_key_set for candidate in self.follow_up_candidates):
            raise ValueError("follow-up candidates require a matching factor update")
        if self.intent == LegalTurnIntent.social and any(
            (
                self.legal_issue,
                self.case_type,
                self.parties,
                self.claims,
                self.key_facts,
                self.disputed_issues,
                self.evidence_notes,
                self.factor_updates,
                self.follow_up_candidates,
            )
        ):
            raise ValueError("social turns cannot contain case analysis")
        return self


class LegalTurnPreparation(BaseModel):
    intent: LegalTurnIntent = Field(
        description=(
            "Classify as social, factual case_update, or legal_question. A factual supplement "
            "without a new question is case_update; the application may resume saved targets."
        )
    )
    legal_issue: str | None = Field(
        default=None,
        max_length=300,
        description="Single legal issue being answered; required for legal_question only.",
    )
    case_type: str | None = Field(
        default=None,
        max_length=200,
        description="Concise matter type supported by the user's wording; omit when unclear.",
    )
    parties: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Parties and roles explicitly identified by the user.",
    )
    claims: list[str] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Relief, outcome, or action explicitly sought by the user. Never place factual "
            "supplements, evidence, or a paraphrase of the message here."
        ),
    )
    key_facts: list[str] = Field(
        default_factory=list,
        max_length=16,
        description=(
            "Every concise factual statement explicitly supplied in the current user turn. "
            "Preserve uncertainty, negation scope, and qualifiers."
        ),
    )
    disputed_issues: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Disputes expressly raised by the user; do not invent inferred disputes.",
    )
    evidence_notes: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Evidence the user says exists or can be obtained; never infer evidence.",
    )
    authority_queries: list[str] = Field(
        default_factory=list,
        max_length=3,
        description=(
            "Up to three focused searches for governing rules and outcome-changing dimensions."
        ),
    )
    material_query: str | None = Field(
        default=None,
        max_length=300,
        description="Search submitted case materials only when their contents can affect the answer.",
    )
    case_law_query: str | None = Field(
        default=None,
        max_length=300,
        description="Search reviewed cases only when a factual comparison materially helps.",
    )
    answer_targets: list[LegalTurnAnswerTarget] = Field(
        default_factory=list,
        max_length=4,
        description="Every question the user asks this turn, without adding issues.",
    )
    follow_up_candidates: list[LegalTurnFollowUpCandidate] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "Only unresolved atomic factors that can change liability, legal range, amount, or "
            "next action. Application review decides whether any question is admitted."
        ),
    )
    factor_updates: list[LegalTurnFactorUpdate] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Small set of current-turn case facts. Never include legal rules, offenses, liability, "
            "predictions, or generic warnings."
        ),
    )

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
