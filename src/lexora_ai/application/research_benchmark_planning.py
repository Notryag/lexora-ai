from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256

from lexora_ai.domain.research_benchmarks import (
    ResearchBenchmarkPlan,
    ResearchRelevanceLoadResult,
)
from lexora_ai.domain.research_datasets import ResearchDatasetLoadResult

RESEARCH_BENCHMARK_VERSION = "research-benchmark-v1"


def build_research_benchmark_plan(
    sources: list[tuple[ResearchDatasetLoadResult, ResearchRelevanceLoadResult]],
) -> ResearchBenchmarkPlan:
    summaries: list[dict[str, object]] = []
    total_queries = 0
    judged_queries = 0
    queries_without_judgments = 0
    orphan_judgment_queries = 0
    total_judgments = 0
    candidates: set[tuple[str, str]] = set()
    integrity_errors: list[str] = []

    for queries, relevance in sources:
        if queries.dataset_name != relevance.dataset_name:
            raise ValueError("query and relevance datasets do not match")
        query_ids = _query_ids(queries)
        judged_ids = {judgment.query_source_id for judgment in relevance.judgments}
        matched = query_ids & judged_ids
        missing = query_ids - judged_ids
        orphaned = judged_ids - query_ids
        grade_counts = Counter(judgment.grade for judgment in relevance.judgments)
        dataset_candidates = {judgment.candidate_source_id for judgment in relevance.judgments}
        total_queries += len(query_ids)
        judged_queries += len(matched)
        queries_without_judgments += len(missing)
        orphan_judgment_queries += len(orphaned)
        total_judgments += len(relevance.judgments)
        candidates.update((queries.dataset_name, item) for item in dataset_candidates)
        if queries.records_rejected:
            integrity_errors.append(f"{queries.dataset_name}: query records were rejected")
        if queries.stopped_at_limit:
            integrity_errors.append(f"{queries.dataset_name}: query loading stopped at limit")
        if relevance.records_rejected:
            integrity_errors.append(f"{queries.dataset_name}: relevance records were rejected")
        if missing:
            integrity_errors.append(f"{queries.dataset_name}: queries are missing judgments")
        if orphaned:
            integrity_errors.append(f"{queries.dataset_name}: judgments reference unknown queries")
        summaries.append(
            {
                "dataset_name": queries.dataset_name,
                "dataset_version": queries.dataset_version,
                "query_source_sha256": queries.source_sha256,
                "relevance_source_sha256": relevance.source_sha256,
                "source_hashes_verified": (
                    queries.source_hash_verified and relevance.source_hash_verified
                ),
                "license_review_status": queries.license_review_status,
                "permitted_scopes": list(queries.permitted_scopes),
                "queries": len(query_ids),
                "queries_rejected": queries.records_rejected,
                "queries_stopped_at_limit": queries.stopped_at_limit,
                "judged_queries": len(matched),
                "queries_without_judgments": len(missing),
                "orphan_judgment_queries": len(orphaned),
                "judgments": len(relevance.judgments),
                "judgments_rejected": relevance.records_rejected,
                "judgments_duplicated": relevance.records_duplicated,
                "distinct_candidates": len(dataset_candidates),
                "grade_distribution": {
                    str(grade): count for grade, count in sorted(grade_counts.items())
                },
            }
        )

    return ResearchBenchmarkPlan(
        benchmark_version=RESEARCH_BENCHMARK_VERSION,
        plan_identity=_plan_identity(summaries),
        datasets=tuple(summaries),
        total_queries=total_queries,
        judged_queries=judged_queries,
        queries_without_judgments=queries_without_judgments,
        orphan_judgment_queries=orphan_judgment_queries,
        total_judgments=total_judgments,
        distinct_candidates=len(candidates),
        integrity_ready=not integrity_errors,
        integrity_errors=tuple(integrity_errors),
    )


def _query_ids(source: ResearchDatasetLoadResult) -> set[str]:
    if source.dataset_name == "cail2022-lcr":
        values = [
            alias.removeprefix("ridx:")
            for record in source.records
            for alias in record.source_aliases
            if alias.startswith("ridx:")
        ]
    else:
        values = [record.source_record_id for record in source.records]
    if len(values) != len(set(values)):
        raise ValueError(f"benchmark query IDs are not unique: {source.dataset_name}")
    return set(values)


def _plan_identity(summaries: list[dict[str, object]]) -> str:
    payload = {
        "benchmark_version": RESEARCH_BENCHMARK_VERSION,
        "datasets": summaries,
    }
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{sha256(rendered.encode()).hexdigest()}"
