from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from lexora_ai.domain.case_law import CaseLawCitation
from lexora_ai.domain.cases import CaseMaterial, MaterialKind
from lexora_ai.domain.legal_knowledge import LegalCitation


class CaseProfile(BaseModel):
    case_type: str | None = Field(default=None, max_length=120)
    parties: list[str] = Field(default_factory=list, max_length=20)
    claims: list[str] = Field(default_factory=list, max_length=20)
    key_facts: list[str] = Field(default_factory=list, max_length=30)
    disputed_issues: list[str] = Field(default_factory=list, max_length=20)
    evidence_notes: list[str] = Field(default_factory=list, max_length=30)
    missing_information: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("case_type")
    @classmethod
    def normalize_case_type(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator(
        "parties",
        "claims",
        "key_facts",
        "disputed_issues",
        "evidence_notes",
        "missing_information",
        mode="before",
    )
    @classmethod
    def normalize_items(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)
                continue
            text = item.strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized

    @field_validator("parties")
    @classmethod
    def validate_parties(cls, value: list[str]) -> list[str]:
        if any(len(item) > 200 for item in value):
            raise ValueError("each party must contain at most 200 characters")
        return value

    @field_validator(
        "claims",
        "disputed_issues",
        "evidence_notes",
        "missing_information",
    )
    @classmethod
    def validate_short_items(cls, value: list[str]) -> list[str]:
        if any(len(item) > 500 for item in value):
            raise ValueError("each item must contain at most 500 characters")
        return value

    @field_validator("key_facts")
    @classmethod
    def validate_key_facts(cls, value: list[str]) -> list[str]:
        if any(len(item) > 1_000 for item in value):
            raise ValueError("each key fact must contain at most 1000 characters")
        return value

    def retrieval_text(self) -> str:
        values = [
            self.case_type,
            *self.parties,
            *self.claims,
            *self.key_facts,
            *self.disputed_issues,
            *self.evidence_notes,
            *self.missing_information,
        ]
        return " ".join(value for value in values if value)


class LegalCaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    background: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def normalize(self) -> LegalCaseCreate:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title cannot be blank")
        if self.background is not None:
            self.background = self.background.strip() or None
        return self


class LegalCase(BaseModel):
    id: UUID
    title: str
    background: str | None
    profile: CaseProfile = Field(default_factory=CaseProfile)
    material_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class LegalCaseUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def normalize(self) -> LegalCaseUpdate:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title cannot be blank")
        return self


class CaseProfileUpdate(CaseProfile):
    pass


class StoredCaseMaterial(CaseMaterial):
    case_id: UUID
    reference_index: int = Field(ge=1)
    original_filename: str | None = None
    media_type: str | None = None
    created_at: datetime


class StoredMaterialChunk(BaseModel):
    id: UUID
    case_id: UUID
    material_id: UUID
    reference: str
    title: str
    kind: MaterialKind
    source_note: str | None
    content: str
    embedding: list[float] | None = None
    embedding_model: str | None = None


class CaseConversationTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)

    @model_validator(mode="after")
    def normalize(self) -> CaseConversationTurnRequest:
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("message cannot be blank")
        return self


class CaseConversationTurnResult(BaseModel):
    case_id: UUID
    thread_id: UUID
    run_id: UUID
    assistant_message: str
    material_count: int = Field(ge=0)
    legal_citations: list[LegalCitation] = Field(default_factory=list)
    case_law_citations: list[CaseLawCitation] = Field(default_factory=list)


class CaseConversationMessage(BaseModel):
    id: UUID
    thread_id: UUID
    run_id: UUID
    role: str
    content: str
    legal_citations: list[LegalCitation] = Field(default_factory=list)
    case_law_citations: list[CaseLawCitation] = Field(default_factory=list)
    created_at: datetime


class MaterialUploadMetadata(BaseModel):
    kind: MaterialKind = MaterialKind.other
    source_note: str | None = Field(default=None, max_length=500)
