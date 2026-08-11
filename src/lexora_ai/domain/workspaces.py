from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from lexora_ai.domain.case_law import CaseLawCitation
from lexora_ai.domain.cases import CaseMaterial, MaterialKind
from lexora_ai.domain.factors import CaseFactorProfile
from lexora_ai.domain.legal_knowledge import LegalCitation


class CaseProfile(BaseModel):
    case_type: str | None = Field(default=None, max_length=120)
    parties: list[str] = Field(default_factory=list, max_length=20)
    claims: list[str] = Field(default_factory=list, max_length=20)
    key_facts: list[str] = Field(default_factory=list, max_length=30)
    disputed_issues: list[str] = Field(default_factory=list, max_length=20)
    evidence_notes: list[str] = Field(default_factory=list, max_length=30)
    missing_information: list[str] = Field(default_factory=list, max_length=30)
    factor_profile: CaseFactorProfile = Field(default_factory=CaseFactorProfile)

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
            self.factor_profile.retrieval_text(),
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


class CaseProfilePatch(BaseModel):
    case_type: str | None = Field(
        default=None,
        max_length=120,
        description="用户当前问题明确涉及的案件类型；不能确定时不要填写",
    )
    parties: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确提到的当事人及其身份",
    )
    claims: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确表达的诉求，不添加模型建议",
    )
    key_facts: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户当前消息明确陈述或确认的简洁案件事实",
    )
    disputed_issues: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确指出的争议，不添加模型推断的争点",
    )
    evidence_notes: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确提到已经持有或可以取得的证据线索",
    )
    missing_information: list[str] | None = Field(
        default=None,
        max_length=10,
        description="更新后仍需用户补充的完整清单；提供时替换原清单，空列表表示已经补齐",
    )
    resolved_missing_information: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户本轮已经回答的待补信息原文，必须与当前档案中的条目一致",
    )
    factor_profile: CaseFactorProfile | None = Field(
        default=None,
        description="应用层维护的结构化案件要素画像；仅接受受控更新",
    )

    @model_validator(mode="after")
    def normalize_and_validate(self) -> CaseProfilePatch:
        self.case_type = self.case_type.strip() or None if self.case_type is not None else None
        for field_name in (
            "parties",
            "claims",
            "key_facts",
            "disputed_issues",
            "evidence_notes",
            "resolved_missing_information",
        ):
            normalized: list[str] = []
            for item in getattr(self, field_name):
                text = item.strip()
                if text and text not in normalized:
                    normalized.append(text)
            setattr(self, field_name, normalized)
        if self.missing_information is not None:
            normalized_missing: list[str] = []
            for item in self.missing_information:
                text = item.strip()
                if text and text not in normalized_missing:
                    normalized_missing.append(text)
            self.missing_information = normalized_missing
        has_additions = any(
            getattr(self, field_name)
            for field_name in (
                "parties",
                "claims",
                "key_facts",
                "disputed_issues",
                "evidence_notes",
                "resolved_missing_information",
            )
        )
        if (
            self.case_type is None
            and self.missing_information is None
            and self.factor_profile is None
            and not has_additions
        ):
            raise ValueError("case profile patch cannot be empty")
        return self

    def apply(self, profile: CaseProfile) -> CaseProfile:
        def merged(existing: list[str], additions: list[str]) -> list[str]:
            result = list(existing)
            result.extend(item for item in additions if item not in result)
            return result

        missing_information = (
            list(self.missing_information)
            if self.missing_information is not None
            else list(profile.missing_information)
        )
        resolved = set(self.resolved_missing_information)
        return CaseProfile(
            case_type=self.case_type or profile.case_type,
            parties=merged(profile.parties, self.parties),
            claims=merged(profile.claims, self.claims),
            key_facts=merged(profile.key_facts, self.key_facts),
            disputed_issues=merged(profile.disputed_issues, self.disputed_issues),
            evidence_notes=merged(profile.evidence_notes, self.evidence_notes),
            missing_information=[item for item in missing_information if item not in resolved],
            factor_profile=self.factor_profile or profile.factor_profile,
        )


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
    profile_updated: bool = False
    case_profile: CaseProfile = Field(default_factory=CaseProfile)


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
