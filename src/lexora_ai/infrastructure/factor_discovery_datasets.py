from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from lexora_ai.domain.factor_discovery import (
    FactorDiscoveryBudget,
    FactorDiscoveryCandidate,
    FactorDiscoveryLoadResult,
)


def normalize_issue(value: str) -> str:
    normalized = value.strip()
    return normalized[:-1] if normalized.endswith("罪") else normalized


def load_factor_discovery_candidates(
    path: Path,
    *,
    dataset_format: str,
    issue: str,
    budget: FactorDiscoveryBudget,
) -> FactorDiscoveryLoadResult:
    if dataset_format not in {"cail2018", "synthetic"}:
        raise ValueError(f"unsupported factor discovery dataset format: {dataset_format}")
    target_issue = normalize_issue(issue)
    requested = budget.discovery_cases + budget.evaluation_cases
    pool_limit = requested * budget.candidate_pool_multiplier
    candidates: list[FactorDiscoveryCandidate] = []
    seen_source_hashes: set[str] = set()
    records_scanned = 0
    records_rejected = 0
    records_duplicated = 0
    stopped_at_pool_limit = False

    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            if records_scanned >= budget.max_records_scanned:
                break
            if not raw_line.strip():
                continue
            records_scanned += 1
            try:
                payload = json.loads(raw_line)
                candidate = (
                    _normalize_cail(payload, target_issue, budget.max_case_chars)
                    if dataset_format == "cail2018"
                    else _normalize_synthetic(payload, target_issue, budget.max_case_chars)
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                records_rejected += 1
                continue
            if candidate is None:
                continue
            if candidate.source_hash in seen_source_hashes:
                records_duplicated += 1
                continue
            seen_source_hashes.add(candidate.source_hash)
            candidates.append(candidate)
            if len(candidates) >= pool_limit:
                stopped_at_pool_limit = True
                break

    return FactorDiscoveryLoadResult(
        candidates=tuple(candidates),
        records_scanned=records_scanned,
        records_rejected=records_rejected,
        records_duplicated=records_duplicated,
        stopped_at_pool_limit=stopped_at_pool_limit,
    )


def _normalize_cail(
    payload: object,
    target_issue: str,
    max_case_chars: int,
) -> FactorDiscoveryCandidate | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
        raise ValueError("invalid CAIL record")
    meta = payload["meta"]
    accusations = meta.get("accusation")
    if not isinstance(accusations, list) or target_issue not in {
        normalize_issue(item) for item in accusations if isinstance(item, str)
    }:
        return None
    facts = _bounded_facts(payload.get("fact"), max_case_chars)
    sentence = meta.get("term_of_imprisonment")
    if not isinstance(sentence, dict):
        raise ValueError("CAIL record has no sentence label")
    outcome_bucket = _sentence_bucket(
        imprisonment=sentence.get("imprisonment"),
        life_imprisonment=sentence.get("life_imprisonment"),
        death_penalty=sentence.get("death_penalty"),
    )
    source_hash = sha256(facts.encode("utf-8")).hexdigest()
    return FactorDiscoveryCandidate(
        id=source_hash[:24],
        issue=target_issue,
        facts=facts,
        outcome_bucket=outcome_bucket,
        source_hash=source_hash,
    )


def _normalize_synthetic(
    payload: object,
    target_issue: str,
    max_case_chars: int,
) -> FactorDiscoveryCandidate | None:
    if not isinstance(payload, dict):
        raise ValueError("invalid synthetic record")
    charge = payload.get("charge")
    if not isinstance(charge, str) or normalize_issue(charge) != target_issue:
        return None
    facts = _bounded_facts(payload.get("fact"), max_case_chars)
    months = payload.get("label_months")
    if not isinstance(months, int | float):
        raise ValueError("synthetic record has no sentence label")
    source_hash = sha256(facts.encode("utf-8")).hexdigest()
    case_id = payload.get("id")
    return FactorDiscoveryCandidate(
        id=str(case_id).strip() if case_id else source_hash[:24],
        issue=target_issue,
        facts=facts,
        outcome_bucket=_sentence_bucket(imprisonment=months),
        source_hash=source_hash,
    )


def _bounded_facts(value: object, max_case_chars: int) -> str:
    if not isinstance(value, str):
        raise ValueError("case facts must be text")
    facts = value.strip()
    if not facts or len(facts) > max_case_chars:
        raise ValueError("case facts are empty or exceed max_case_chars")
    return facts


def _sentence_bucket(
    *,
    imprisonment: object,
    life_imprisonment: object = False,
    death_penalty: object = False,
) -> str:
    if death_penalty is True:
        return "death"
    if life_imprisonment is True:
        return "life"
    if not isinstance(imprisonment, int | float):
        raise ValueError("sentence imprisonment must be numeric")
    if imprisonment <= 0:
        return "non_custodial"
    if imprisonment <= 12:
        return "up_to_12_months"
    if imprisonment <= 36:
        return "13_to_36_months"
    return "over_36_months"
