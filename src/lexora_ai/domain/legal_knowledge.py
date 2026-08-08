from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

MAX_LEGAL_SOURCE_CHARS = 500_000


class LegalSourceKind(StrEnum):
    law = "law"
    administrative_regulation = "administrative_regulation"
    judicial_interpretation = "judicial_interpretation"
    department_rule = "department_rule"
    local_regulation = "local_regulation"
    other = "other"


class LegalSourceStatus(StrEnum):
    effective = "effective"
    amended = "amended"
    repealed = "repealed"
    not_effective = "not_effective"


class LegalSourceReviewStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class LegalSourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: LegalSourceKind
    issuing_authority: str = Field(min_length=1, max_length=300)
    status: LegalSourceStatus
    published_on: date | None = None
    effective_on: date | None = None
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2_000)
    version_label: str | None = Field(default=None, max_length=200)
    content: str = Field(min_length=1, max_length=MAX_LEGAL_SOURCE_CHARS)
    review_status: LegalSourceReviewStatus = LegalSourceReviewStatus.approved
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_and_validate(self) -> LegalSourceCreate:
        self.title = self.title.strip()
        self.issuing_authority = self.issuing_authority.strip()
        self.source_name = self.source_name.strip()
        self.source_url = self.source_url.strip()
        self.content = self.content.strip()
        self.version_label = self.version_label.strip() or None if self.version_label else None
        parsed = urlparse(self.source_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (hostname == "gov.cn" or hostname.endswith(".gov.cn")):
            raise ValueError("source_url must be an official HTTPS *.gov.cn address")
        if not self.title or not self.issuing_authority or not self.source_name or not self.content:
            raise ValueError("legal source text fields cannot be blank")
        if self.review_status == LegalSourceReviewStatus.approved and self.verified_at is None:
            self.verified_at = datetime.now(UTC)
        if self.review_status != LegalSourceReviewStatus.approved:
            self.verified_at = None
        return self


class LegalSourceSummary(BaseModel):
    id: UUID
    title: str
    kind: LegalSourceKind
    issuing_authority: str
    status: LegalSourceStatus
    published_on: date | None
    effective_on: date | None
    source_name: str
    source_url: str
    version_label: str | None
    review_status: LegalSourceReviewStatus
    content_sha256: str
    verified_at: datetime | None
    chunk_count: int = Field(ge=0)
    created_at: datetime


class LegalSourceUpdate(BaseModel):
    status: LegalSourceStatus | None = None
    review_status: LegalSourceReviewStatus | None = None
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def validate_update(self) -> LegalSourceUpdate:
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


class LegalSourceDetail(LegalSourceSummary):
    content: str


class LegalKnowledgeChunk(BaseModel):
    id: UUID
    source_id: UUID
    reference: str
    article_label: str | None
    heading_path: tuple[str, ...] = ()
    title: str
    issuing_authority: str
    source_url: str
    status: LegalSourceStatus
    content: str
    embedding: list[float] | None = None
    embedding_model: str | None = None


class LegalCitation(BaseModel):
    reference: str
    title: str
    article_label: str | None
    issuing_authority: str
    source_url: str
    status: LegalSourceStatus
