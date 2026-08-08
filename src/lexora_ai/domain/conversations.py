from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from lexora_ai.domain.cases import (
    LEGAL_ANALYSIS_DISCLAIMER,
    MAX_MATERIALS,
    MAX_TOTAL_MATERIAL_CHARS,
    CaseMaterial,
)
from lexora_ai.domain.workspaces import CaseProfile


class ConversationTurnRequest(BaseModel):
    thread_id: UUID | None = None
    message: str = Field(min_length=1, max_length=4_000)
    case_title: str | None = Field(default=None, max_length=240)
    case_profile: CaseProfile | None = None
    materials: list[CaseMaterial] = Field(default_factory=list, max_length=MAX_MATERIALS)

    @model_validator(mode="after")
    def validate_turn(self) -> ConversationTurnRequest:
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("message cannot be blank")
        total_chars = sum(len(material.content) for material in self.materials)
        if total_chars > MAX_TOTAL_MATERIAL_CHARS:
            raise ValueError(
                f"total material content must contain at most {MAX_TOTAL_MATERIAL_CHARS} characters"
            )
        return self


class ConversationTurnResult(BaseModel):
    thread_id: UUID
    assistant_message: str
    material_count: int = Field(ge=0)
    disclaimer: str = LEGAL_ANALYSIS_DISCLAIMER
