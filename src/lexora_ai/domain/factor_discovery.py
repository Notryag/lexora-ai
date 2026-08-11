from __future__ import annotations

from dataclasses import asdict, dataclass

from pydantic import BaseModel, Field, model_validator


class FactorDiscoveryBudget(BaseModel):
    discovery_cases: int = Field(default=120, ge=1, le=1_000)
    evaluation_cases: int = Field(default=60, ge=1, le=1_000)
    max_unique_cases: int = Field(default=180, ge=2, le=2_000)
    max_model_calls: int = Field(default=30, ge=1, le=500)
    max_input_tokens: int = Field(default=300_000, ge=1_000, le=10_000_000)
    max_output_tokens: int = Field(default=40_000, ge=1_000, le=2_000_000)
    max_batch_input_tokens: int = Field(default=20_000, ge=1_000, le=100_000)
    max_records_scanned: int = Field(default=50_000, ge=1, le=5_000_000)
    candidate_pool_multiplier: int = Field(default=4, ge=1, le=20)
    max_case_chars: int = Field(default=6_000, ge=500, le=40_000)

    @model_validator(mode="after")
    def validate_case_budget(self) -> FactorDiscoveryBudget:
        requested = self.discovery_cases + self.evaluation_cases
        if requested > self.max_unique_cases:
            raise ValueError("discovery_cases + evaluation_cases exceeds max_unique_cases")
        return self


@dataclass(frozen=True, slots=True)
class FactorDiscoveryCandidate:
    id: str
    issue: str
    facts: str
    outcome_bucket: str
    source_hash: str


@dataclass(frozen=True, slots=True)
class FactorDiscoveryLoadResult:
    candidates: tuple[FactorDiscoveryCandidate, ...]
    records_scanned: int
    records_rejected: int
    records_duplicated: int
    stopped_at_pool_limit: bool


@dataclass(frozen=True, slots=True)
class FactorDiscoveryBatch:
    stage: str
    case_ids: tuple[str, ...]
    estimated_input_tokens: int
    cache_key: str


@dataclass(frozen=True, slots=True)
class FactorDiscoveryPlan:
    dataset_name: str
    dataset_version: str
    dataset_identity: str
    dataset_identity_declared: bool
    license_review_status: str
    issue: str
    sampling_seed: int
    records_scanned: int
    records_rejected: int
    records_duplicated: int
    eligible_candidates: int
    selected_discovery_ids: tuple[str, ...]
    selected_evaluation_ids: tuple[str, ...]
    selected_by_outcome: dict[str, int]
    batches: tuple[FactorDiscoveryBatch, ...]
    estimated_model_calls: int
    estimated_input_tokens: int
    reserved_output_tokens: int
    within_budget: bool
    budget_errors: tuple[str, ...]
    execution_ready: bool
    readiness_errors: tuple[str, ...]
    stopped_at_pool_limit: bool
    dry_run: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
