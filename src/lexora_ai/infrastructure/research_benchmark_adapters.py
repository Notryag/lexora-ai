from __future__ import annotations

import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from lexora_ai.domain.research_benchmarks import (
    ResearchCandidateInventory,
    ResearchRelevanceJudgment,
    ResearchRelevanceLoadResult,
)

SUPPORTED_RELEVANCE_DATASETS = frozenset({"cail2022-lcr", "lecardv2", "stard"})


def load_stard_candidate_inventory(
    path: Path,
    *,
    expected_source_sha256: str,
    max_file_bytes: int = 32 * 1024 * 1024,
    max_candidates: int = 60_000,
    max_text_chars: int = 20_000,
) -> ResearchCandidateInventory:
    if max_file_bytes <= 0 or max_candidates <= 0 or max_text_chars <= 0:
        raise ValueError("candidate inventory limits must be positive")
    size, source_hash = _verify_source(
        path,
        expected_source_sha256=expected_source_sha256,
        max_file_bytes=max_file_bytes,
        label="candidate corpus",
    )
    candidate_ids: set[str] = set()
    rejected = 0
    scanned = 0
    rejection_reasons: Counter[str] = Counter()
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            if not raw_line.strip():
                continue
            if scanned >= max_candidates:
                raise ValueError("candidate corpus exceeds max_candidates")
            scanned += 1
            try:
                payload = json.loads(raw_line)
                if not isinstance(payload, dict):
                    raise ValueError("candidate record must be an object")
                candidate_id = _identifier(payload.get("id"), "candidate ID")
                name = payload.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("candidate name is invalid")
                content = payload.get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("candidate content is invalid")
                if len(content) > max_text_chars:
                    raise ValueError("candidate content exceeds max_text_chars")
                if candidate_id in candidate_ids:
                    raise ValueError("candidate ID is duplicated")
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                rejected += 1
                rejection_reasons[str(error)] += 1
                continue
            candidate_ids.add(candidate_id)
    return ResearchCandidateInventory(
        dataset_name="stard",
        candidate_ids=frozenset(candidate_ids),
        records_scanned=scanned,
        records_rejected=rejected,
        rejection_reasons=dict(sorted(rejection_reasons.items())),
        source_sha256=source_hash,
        source_size_bytes=size,
        source_hash_verified=True,
    )


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
    size, source_hash = _verify_source(
        path,
        expected_source_sha256=expected_source_sha256,
        max_file_bytes=max_file_bytes,
        label="relevance source",
    )

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


def _verify_source(
    path: Path,
    *,
    expected_source_sha256: str,
    max_file_bytes: int,
    label: str,
) -> tuple[int, str]:
    size = path.stat().st_size
    if size > max_file_bytes:
        raise ValueError(f"{label} exceeds max_file_bytes")
    source_hash = _file_sha256(path)
    expected = expected_source_sha256.strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError(f"expected {label} SHA-256 is invalid")
    if source_hash != expected:
        raise ValueError(f"{label} SHA-256 does not match source registry")
    return size, source_hash
