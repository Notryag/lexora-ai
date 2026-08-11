from __future__ import annotations

import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

from lexora_ai.domain.factor_discovery import (
    FactorDiscoveryBatch,
    FactorDiscoveryBudget,
    FactorDiscoveryCandidate,
    FactorDiscoveryPlan,
)
from lexora_ai.infrastructure.factor_discovery_datasets import (
    load_factor_discovery_candidates,
)

NORMALIZATION_VERSION = "factor-discovery-v1"
DISCOVERY_PROMPT_VERSION = "bottom-up-factors-v1"
EXTRACTION_PROMPT_VERSION = "factor-extraction-v1"


def build_factor_discovery_plan(
    path: Path,
    *,
    dataset_format: str,
    dataset_name: str,
    dataset_version: str,
    dataset_sha256: str | None,
    issue: str,
    sampling_seed: int,
    model: str,
    budget: FactorDiscoveryBudget,
) -> FactorDiscoveryPlan:
    identity, declared = _dataset_identity(path, dataset_sha256)
    loaded = load_factor_discovery_candidates(
        path,
        dataset_format=dataset_format,
        issue=issue,
        budget=budget,
    )
    ordered = _stratified_order(loaded.candidates, sampling_seed)
    discovery_count, evaluation_count = _split_counts(len(ordered), budget)
    discovery = ordered[:discovery_count]
    evaluation = ordered[discovery_count : discovery_count + evaluation_count]

    discovery_batches = _pack_batches(
        discovery,
        stage="discovery",
        dataset_identity=identity,
        model=model,
        prompt_version=DISCOVERY_PROMPT_VERSION,
        max_tokens=budget.max_batch_input_tokens,
    )
    evaluation_batches = _pack_batches(
        evaluation,
        stage="extraction_evaluation",
        dataset_identity=identity,
        model=model,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        max_tokens=budget.max_batch_input_tokens,
    )
    batches = (*discovery_batches, *evaluation_batches)
    merge_calls = 1 if discovery_batches else 0
    estimated_model_calls = len(batches) + merge_calls
    estimated_input_tokens = sum(batch.estimated_input_tokens for batch in batches)
    reserved_output_tokens = budget.max_output_tokens
    budget_errors: list[str] = []
    if estimated_model_calls > budget.max_model_calls:
        budget_errors.append("estimated model calls exceed max_model_calls")
    if estimated_input_tokens > budget.max_input_tokens:
        budget_errors.append("estimated input tokens exceed max_input_tokens")
    if any(
        batch.estimated_input_tokens > budget.max_batch_input_tokens for batch in batches
    ):
        budget_errors.append("a batch exceeds max_batch_input_tokens")
    if len(discovery) + len(evaluation) > budget.max_unique_cases:
        budget_errors.append("selected cases exceed max_unique_cases")
    selected_by_outcome = Counter(case.outcome_bucket for case in (*discovery, *evaluation))
    readiness_errors = list(budget_errors)
    if not declared:
        readiness_errors.append("dataset SHA-256 has not been declared from an acquisition check")
    if len(discovery) < budget.discovery_cases:
        readiness_errors.append("discovery sample is smaller than the requested size")
    if len(evaluation) < budget.evaluation_cases:
        readiness_errors.append("evaluation sample is smaller than the requested size")

    return FactorDiscoveryPlan(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        dataset_identity=identity,
        dataset_identity_declared=declared,
        issue=issue.strip(),
        sampling_seed=sampling_seed,
        records_scanned=loaded.records_scanned,
        records_rejected=loaded.records_rejected,
        records_duplicated=loaded.records_duplicated,
        eligible_candidates=len(loaded.candidates),
        selected_discovery_ids=tuple(case.id for case in discovery),
        selected_evaluation_ids=tuple(case.id for case in evaluation),
        selected_by_outcome=dict(sorted(selected_by_outcome.items())),
        batches=batches,
        estimated_model_calls=estimated_model_calls,
        estimated_input_tokens=estimated_input_tokens,
        reserved_output_tokens=reserved_output_tokens,
        within_budget=not budget_errors,
        budget_errors=tuple(budget_errors),
        execution_ready=not readiness_errors,
        readiness_errors=tuple(readiness_errors),
        stopped_at_pool_limit=loaded.stopped_at_pool_limit,
    )


def _dataset_identity(path: Path, expected_sha256: str | None) -> tuple[str, bool]:
    if expected_sha256:
        normalized = expected_sha256.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("dataset_sha256 must be a 64-character hexadecimal digest")
        return f"sha256:{normalized}", True
    stat = path.stat()
    return f"unverified:{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}", False


def _stratified_order(
    candidates: tuple[FactorDiscoveryCandidate, ...],
    seed: int,
) -> list[FactorDiscoveryCandidate]:
    strata: dict[str, list[FactorDiscoveryCandidate]] = defaultdict(list)
    for candidate in candidates:
        strata[candidate.outcome_bucket].append(candidate)
    for name, items in strata.items():
        items.sort(key=lambda item: _sampling_rank(seed, name, item.source_hash))
    result: list[FactorDiscoveryCandidate] = []
    names = sorted(strata)
    position = 0
    while names:
        remaining: list[str] = []
        for name in names:
            items = strata[name]
            if position < len(items):
                result.append(items[position])
            if position + 1 < len(items):
                remaining.append(name)
        names = remaining
        position += 1
    return result


def _sampling_rank(seed: int, stratum: str, source_hash: str) -> str:
    return sha256(f"{seed}:{stratum}:{source_hash}".encode()).hexdigest()


def _split_counts(
    available: int,
    budget: FactorDiscoveryBudget,
) -> tuple[int, int]:
    requested = budget.discovery_cases + budget.evaluation_cases
    selected = min(available, requested, budget.max_unique_cases)
    if selected == 0:
        return 0, 0
    if selected == requested:
        return budget.discovery_cases, budget.evaluation_cases
    discovery_share = budget.discovery_cases / requested
    discovery = min(budget.discovery_cases, max(1, round(selected * discovery_share)))
    evaluation = min(budget.evaluation_cases, selected - discovery)
    return discovery, evaluation


def _pack_batches(
    cases: list[FactorDiscoveryCandidate],
    *,
    stage: str,
    dataset_identity: str,
    model: str,
    prompt_version: str,
    max_tokens: int,
) -> tuple[FactorDiscoveryBatch, ...]:
    batches: list[FactorDiscoveryBatch] = []
    pending: list[FactorDiscoveryCandidate] = []
    pending_tokens = 0
    for case in cases:
        case_tokens = _estimate_case_tokens(case)
        if pending and pending_tokens + case_tokens > max_tokens:
            batches.append(
                _batch(
                    pending,
                    stage=stage,
                    estimated_tokens=pending_tokens,
                    dataset_identity=dataset_identity,
                    model=model,
                    prompt_version=prompt_version,
                )
            )
            pending = []
            pending_tokens = 0
        pending.append(case)
        pending_tokens += case_tokens
    if pending:
        batches.append(
            _batch(
                pending,
                stage=stage,
                estimated_tokens=pending_tokens,
                dataset_identity=dataset_identity,
                model=model,
                prompt_version=prompt_version,
            )
        )
    return tuple(batches)


def _estimate_case_tokens(case: FactorDiscoveryCandidate) -> int:
    return len(case.facts) + 200


def _batch(
    cases: list[FactorDiscoveryCandidate],
    *,
    stage: str,
    estimated_tokens: int,
    dataset_identity: str,
    model: str,
    prompt_version: str,
) -> FactorDiscoveryBatch:
    case_ids = tuple(case.id for case in cases)
    cache_payload = json.dumps(
        {
            "dataset": dataset_identity,
            "normalization": NORMALIZATION_VERSION,
            "prompt": prompt_version,
            "model": model,
            "stage": stage,
            "source_hashes": [case.source_hash for case in cases],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return FactorDiscoveryBatch(
        stage=stage,
        case_ids=case_ids,
        estimated_input_tokens=estimated_tokens,
        cache_key=sha256(cache_payload.encode()).hexdigest(),
    )
