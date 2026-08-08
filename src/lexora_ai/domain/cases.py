from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

MAX_MATERIALS = 20
MAX_MATERIAL_CHARS = 40_000
MAX_TOTAL_MATERIAL_CHARS = 120_000
LEGAL_ANALYSIS_DISCLAIMER = (
    "本分析由 AI 基于所提交材料生成，仅用于案件研究和材料整理，不构成法律意见，"
    "不能替代执业律师对事实、证据及适用法律的审查。"
)


class MaterialKind(StrEnum):
    complaint = "complaint"
    defense = "defense"
    contract = "contract"
    evidence = "evidence"
    transcript = "transcript"
    judgment = "judgment"
    statute = "statute"
    other = "other"


class CaseMaterial(BaseModel):
    material_id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    kind: MaterialKind = MaterialKind.other
    content: str = Field(min_length=1, max_length=MAX_MATERIAL_CHARS)
    source_note: str | None = Field(default=None, max_length=500)


class CaseAnalysisRequest(BaseModel):
    case_title: str = Field(min_length=1, max_length=240)
    case_background: str | None = Field(default=None, max_length=10_000)
    questions: list[str] = Field(default_factory=list, max_length=10)
    materials: list[CaseMaterial] = Field(min_length=1, max_length=MAX_MATERIALS)

    @model_validator(mode="after")
    def validate_analysis_input(self) -> CaseAnalysisRequest:
        normalized_questions: list[str] = []
        for question in self.questions:
            normalized = question.strip()
            if not normalized:
                raise ValueError("questions cannot contain empty values")
            if len(normalized) > 500:
                raise ValueError("each question must contain at most 500 characters")
            if normalized not in normalized_questions:
                normalized_questions.append(normalized)
        self.questions = normalized_questions

        total_chars = sum(len(material.content) for material in self.materials)
        if total_chars > MAX_TOTAL_MATERIAL_CHARS:
            raise ValueError(
                f"total material content must contain at most {MAX_TOTAL_MATERIAL_CHARS} characters"
            )
        return self


class CaseAnalysisResult(BaseModel):
    analysis_id: UUID
    case_title: str
    analysis: str
    material_count: int = Field(ge=1)
    runtime_thread_id: str | None = None
    disclaimer: str = LEGAL_ANALYSIS_DISCLAIMER
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

