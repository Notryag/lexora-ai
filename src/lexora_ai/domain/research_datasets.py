from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class ResearchRecordKind(StrEnum):
    case = "case"
    consultation = "consultation"


@dataclass(frozen=True, slots=True)
class NormalizedResearchRecord:
    dataset_name: str
    dataset_version: str
    source_record_id: str
    source_aliases: tuple[str, ...]
    record_kind: ResearchRecordKind
    text: str
    title: str | None
    case_number: str | None
    labels: tuple[str, ...]
    content_hash: str

    @property
    def reference(self) -> str:
        return f"{self.dataset_name}:{self.source_record_id}"


@dataclass(frozen=True, slots=True)
class ResearchDatasetLoadResult:
    dataset_name: str
    dataset_version: str
    records: tuple[NormalizedResearchRecord, ...]
    records_scanned: int
    records_rejected: int
    rejection_reasons: dict[str, int]
    stopped_at_limit: bool


@dataclass(frozen=True, slots=True)
class ResearchDuplicateGroup:
    identity: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchNormalizationPlan:
    sources: tuple[dict[str, object], ...]
    total_records: int
    unique_records: int
    duplicate_records: int
    duplicate_source_ids: int
    duplicate_case_numbers: int
    duplicate_content_hashes: int
    case_records_without_case_number: int
    consultation_records: int
    cross_source_case_number_groups: tuple[ResearchDuplicateGroup, ...]
    cross_source_content_groups: tuple[ResearchDuplicateGroup, ...]
    dry_run: bool = True
    model_calls: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
