from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from lexora_ai.domain.research_benchmarks import (
    ResearchRelevanceJudgment,
    ResearchRelevanceLoadResult,
)

SUPPORTED_RELEVANCE_DATASETS = frozenset({"cail2022-lcr", "lecardv2", "stard"})


def load_relevance_judgments(
    path: Path,
    *,
    dataset_name: str,
    expected_source_sha256: str,
    max_file_bytes: int = 4 * 1024 * 1024,
    max_judgments: int = 100_000,
) -> ResearchRelevanceLoadResult:
    if dataset_name not in SUPPORTED_RELEVANCE_DATASETS:
        raise ValueError(f"unsupported relevance dataset: {dataset_name}")
    if max_file_bytes <= 0 or max_judgments <= 0:
        raise ValueError("relevance limits must be positive")
    size = path.stat().st_size
    if size > max_file_bytes:
        raise ValueError("relevance source exceeds max_file_bytes")
    source_hash = _file_sha256(path)
    expected = expected_source_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("expected relevance SHA-256 is invalid")
    if source_hash != expected:
        raise ValueError("relevance source SHA-256 does not match source registry")

    raw_judgments = _read_judgments(path, dataset_name)
    judgments: list[ResearchRelevanceJudgment] = []
    seen: dict[tuple[str, str], int] = {}
    rejected = 0
    duplicated = 0
    rejection_reasons: Counter[str] = Counter()
    scanned = 0
    for raw_query_id, raw_candidate_id, raw_grade in raw_judgments:
        if scanned >= max_judgments:
            raise ValueError("relevance source exceeds max_judgments")
        scanned += 1
        try:
            query_id = _identifier(raw_query_id, "query ID")
            candidate_id = _identifier(raw_candidate_id, "candidate ID")
            grade = _grade(raw_grade)
        except (TypeError, ValueError) as error:
            rejected += 1
            rejection_reasons[str(error)] += 1
            continue
        key = (query_id, candidate_id)
        previous_grade = seen.get(key)
        if previous_grade is not None:
            if previous_grade != grade:
                raise ValueError("relevance source contains conflicting grades for one pair")
            duplicated += 1
            continue
        seen[key] = grade
        judgments.append(
            ResearchRelevanceJudgment(
                dataset_name=dataset_name,
                query_source_id=query_id,
                candidate_source_id=candidate_id,
                grade=grade,
            )
        )
    return ResearchRelevanceLoadResult(
        dataset_name=dataset_name,
        judgments=tuple(judgments),
        records_scanned=scanned,
        records_rejected=rejected,
        records_duplicated=duplicated,
        rejection_reasons=dict(sorted(rejection_reasons.items())),
        source_sha256=source_hash,
        source_size_bytes=size,
        source_hash_verified=True,
    )


def _read_judgments(path: Path, dataset_name: str):
    if dataset_name == "lecardv2":
        yield from _read_trec(path)
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if dataset_name == "cail2022-lcr":
        if not isinstance(payload, dict):
            raise ValueError("CAIL2022 relevance source must be an object")
        for query_id, candidates in payload.items():
            if not isinstance(candidates, dict):
                yield query_id, None, None
                continue
            for candidate_id, grade in candidates.items():
                yield query_id, candidate_id, grade
        return
    if not isinstance(payload, list):
        raise ValueError("STARD relevance source must be an array")
    for query in payload:
        if not isinstance(query, dict):
            yield None, None, None
            continue
        candidate_ids = query.get("match_id")
        if not isinstance(candidate_ids, list):
            yield query.get("query_id"), None, None
            continue
        for candidate_id in candidate_ids:
            yield query.get("query_id"), candidate_id, 1


def _read_trec(path: Path):
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            fields = line.split()
            if len(fields) != 4:
                yield None, None, None
                continue
            yield fields[0], fields[2], fields[3]


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str | int) or isinstance(value, bool):
        raise ValueError(f"{label} is invalid")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} is invalid")
    return normalized


def _grade(value: object) -> int:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 3:
        raise ValueError("relevance grade must be between 0 and 3")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
