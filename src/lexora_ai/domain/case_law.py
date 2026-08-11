from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from lexora_ai.domain.legal_knowledge import LegalSourceReviewStatus

MAX_CASE_LAW_CHARS = 500_000


class CaseLawStatus(StrEnum):
    active = "active"
    withdrawn = "withdrawn"


class CaseLawSourceCreate(BaseModel):
    case_number: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    issuing_authority: str = Field(min_length=1, max_length=300)
    status: CaseLawStatus = CaseLawStatus.active
    published_on: date | None = None
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2_000)
    content: str = Field(min_length=1, max_length=MAX_CASE_LAW_CHARS)
    review_status: LegalSourceReviewStatus = LegalSourceReviewStatus.pending
    verified_at: datetime | None = None

    @field_validator("keywords", mode="before")
    @classmethod
    def normalize_keywords(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        for keyword in value:
            if not isinstance(keyword, str):
                normalized.append(keyword)
                continue
            keyword = keyword.strip()
            if keyword and keyword not in normalized:
                normalized.append(keyword)
        return normalized

    @model_validator(mode="after")
    def normalize_and_validate(self) -> CaseLawSourceCreate:
        self.case_number = self.case_number.strip()
        self.title = self.title.strip()
        self.issuing_authority = self.issuing_authority.strip()
        self.source_name = self.source_name.strip()
        self.source_url = self.source_url.strip()
        self.content = self.content.strip()
        parsed = urlparse(self.source_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname == "court.gov.cn" or hostname.endswith(".court.gov.cn")
        ):
            raise ValueError("source_url must be an official HTTPS *.court.gov.cn address")
        if not all(
            (self.case_number, self.title, self.issuing_authority, self.source_name, self.content)
        ):
            raise ValueError("case-law source text fields cannot be blank")
        if self.review_status == LegalSourceReviewStatus.approved and self.verified_at is None:
            self.verified_at = datetime.now(UTC)
        if self.review_status != LegalSourceReviewStatus.approved:
            self.verified_at = None
        return self


class CaseLawSourceSummary(BaseModel):
    id: UUID
    case_number: str
    title: str
    keywords: list[str]
    issuing_authority: str
    status: CaseLawStatus
    published_on: date | None
    source_name: str
    source_url: str
    review_status: LegalSourceReviewStatus
    content_sha256: str
    verified_at: datetime | None
    chunk_count: int = Field(ge=0)
    created_at: datetime


class CaseLawSourceDetail(CaseLawSourceSummary):
    content: str


class CaseLawSourceUpdate(BaseModel):
    status: CaseLawStatus | None = None
    review_status: LegalSourceReviewStatus | None = None
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def validate_update(self) -> CaseLawSourceUpdate:
        if self.status is None and self.review_status is None:
            raise ValueError("status or review_status is required")
        if self.review_status == LegalSourceReviewStatus.approved and self.verified_at is None:
            self.verified_at = datetime.now(UTC)
        if self.review_status in {
            LegalSourceReviewStatus.pending,
            LegalSourceReviewStatus.rejected,
        }:
            self.verified_at = None
        return self


class CaseLawChunk(BaseModel):
    id: UUID
    source_id: UUID
    reference: str
    section_label: str
    case_number: str
    title: str
    keywords: list[str]
    issuing_authority: str
    source_url: str
    published_on: date | None
    content: str
    embedding: list[float] | None = None
    embedding_model: str | None = None


class CaseLawCitation(BaseModel):
    reference: str
    case_number: str
    title: str
    section_label: str
    issuing_authority: str
    source_url: str
    published_on: date | None
    content: str | None = None
