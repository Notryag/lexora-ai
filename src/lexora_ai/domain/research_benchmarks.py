from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ResearchRelevanceJudgment:
    dataset_name: str
    query_source_id: str
    candidate_source_id: str
    grade: int


@dataclass(frozen=True, slots=True)
class ResearchRelevanceLoadResult:
    dataset_name: str
    judgments: tuple[ResearchRelevanceJudgment, ...]
    records_scanned: int
    records_rejected: int
    records_duplicated: int
    rejection_reasons: dict[str, int]
    source_sha256: str
    source_size_bytes: int
    source_hash_verified: bool


@dataclass(frozen=True, slots=True)
class ResearchCandidateInventory:
    dataset_name: str
    candidate_ids: frozenset[str]
    records_scanned: int
    records_rejected: int
    rejection_reasons: dict[str, int]
    source_sha256: str
    source_size_bytes: int
    source_hash_verified: bool


@dataclass(frozen=True, slots=True)
class ResearchBenchmarkPlan:
    benchmark_version: str
    plan_identity: str
    datasets: tuple[dict[str, object], ...]
    total_queries: int
    judged_queries: int
    queries_without_judgments: int
    orphan_judgment_queries: int
    total_judgments: int
    distinct_candidates: int
    integrity_ready: bool
    integrity_errors: tuple[str, ...]
    evaluation_ready: bool
    readiness_errors: tuple[str, ...]
    dry_run: bool = True
    candidate_corpus_scanned: bool = False
    candidate_text_loaded: bool = False
    model_calls: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
