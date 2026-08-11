from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class FactorType(StrEnum):
    text = "text"
    numeric = "numeric"
    boolean = "boolean"
    categorical = "categorical"


class FactorState(StrEnum):
    asserted = "asserted"
    denied = "denied"
    unknown = "unknown"
    conflicting = "conflicting"


class FactorMateriality(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class FactorDefinition(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    type: FactorType
    question: str = Field(min_length=1, max_length=300)
    materiality: FactorMateriality = FactorMateriality.medium
    options: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("key", "label", "question")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result


class CaseFactor(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    type: FactorType
    state: FactorState = FactorState.unknown
    value: bool | int | float | str | None = None
    materiality: FactorMateriality = FactorMateriality.medium
    question: str | None = Field(default=None, max_length=300)
    source_turns: list[int] = Field(default_factory=list, max_length=20)
    source_material_refs: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("key", "label", "question", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("source_turns")
    @classmethod
    def normalize_turns(cls, value: list[int]) -> list[int]:
        result: list[int] = []
        for item in value:
            if item not in result:
                result.append(item)
        return result

    @field_validator("source_material_refs")
    @classmethod
    def normalize_refs(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result


class CaseFactorProfile(BaseModel):
    active_domains: list[str] = Field(default_factory=list, max_length=8)
    factors: list[CaseFactor] = Field(default_factory=list, max_length=80)

    @field_validator("active_domains")
    @classmethod
    def normalize_domains(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result

    def seeded(
        self,
        *,
        domains: list[str],
        definitions: list[FactorDefinition],
    ) -> CaseFactorProfile:
        profile = self.model_copy(deep=True)
        for domain in domains:
            if domain not in profile.active_domains:
                profile.active_domains.append(domain)
        existing = {factor.key: factor for factor in profile.factors}
        for definition in definitions:
            if definition.key in existing:
                continue
            profile.factors.append(
                CaseFactor(
                    key=definition.key,
                    label=definition.label,
                    type=definition.type,
                    state=FactorState.unknown,
                    materiality=definition.materiality,
                    question=definition.question,
                )
            )
        return profile

    def retrieval_text(self) -> str:
        values = [*self.active_domains]
        for factor in self.factors:
            if factor.state == FactorState.unknown:
                continue
            if factor.value is None:
                values.append(factor.label)
                continue
            values.append(f"{factor.label}:{factor.value}")
        return " ".join(value for value in values if value)

    def apply_updates(
        self,
        updates: list[object],
    ) -> CaseFactorProfile:
        from lexora_ai.domain.legal_turns import LegalTurnFactorUpdate

        profile = self.model_copy(deep=True)
        by_key = {factor.key: factor for factor in profile.factors}
        for update in updates:
            if not isinstance(update, LegalTurnFactorUpdate):
                update = LegalTurnFactorUpdate.model_validate(update)
            factor = by_key.get(update.key)
            if factor is None:
                if len(profile.factors) >= 80:
                    break
                factor = CaseFactor(
                    key=update.key,
                    label=update.label,
                    type=update.type,
                    state=update.state,
                    value=update.value,
                    materiality=update.materiality,
                    question=update.question,
                )
                profile.factors.append(factor)
                by_key[factor.key] = factor
                continue
            factor.state = update.state
            factor.value = update.value
            factor.materiality = update.materiality
            if update.question:
                factor.question = update.question
        return profile
