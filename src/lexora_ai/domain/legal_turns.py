from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from lexora_ai.domain.factors import FactorState


class LegalTurnIntent(StrEnum):
    social = "social"
    case_update = "case_update"
    legal_question = "legal_question"


class LegalTurnFactorUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    state: FactorState
    value: bool | int | float | str | None = None

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
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
    decision_variables: list[str] = Field(default_factory=list, max_length=2)
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
        "decision_variables",
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
        if self.intent == LegalTurnIntent.social and any(
            (
                self.legal_issue,
                self.authority_queries,
                self.material_query,
                self.case_law_query,
                self.decision_variables,
                self.factor_updates,
            )
        ):
            raise ValueError("social turns cannot request legal analysis")
        return self
