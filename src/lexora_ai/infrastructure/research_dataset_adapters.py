from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

from lexora_ai.domain.research_datasets import (
    NormalizedResearchRecord,
    ResearchDatasetLoadResult,
    ResearchRecordKind,
)

SUPPORTED_RESEARCH_DATASETS = frozenset({"cail2022-lcr", "lecardv2", "stard"})
_CASE_NUMBER_PATTERN = re.compile(
    r"\((?P<year>\d{4})\)(?P<body>[\u4e00-\u9fffA-Za-z0-9]{1,30}?)(?:第)?(?P<serial>\d{1,10})号"
)


def load_research_dataset(
    path: Path,
    *,
    dataset_name: str,
    dataset_version: str,
    max_records: int = 5_000,
    max_text_chars: int = 30_000,
    max_file_bytes: int = 32 * 1024 * 1024,
    expected_source_sha256: str | None = None,
    license_review_status: str = "unrecorded",
    permitted_scopes: tuple[str, ...] = (),
) -> ResearchDatasetLoadResult:
    if dataset_name not in SUPPORTED_RESEARCH_DATASETS:
        raise ValueError(f"unsupported research dataset: {dataset_name}")
    if max_records <= 0 or max_text_chars <= 0 or max_file_bytes <= 0:
        raise ValueError("normalization limits must be positive")
    source_size_bytes = path.stat().st_size
    if source_size_bytes > max_file_bytes:
        raise ValueError("research dataset exceeds max_file_bytes")
    source_sha256 = _file_sha256(path)
    source_hash_verified = False
    if expected_source_sha256 is not None:
        expected = expected_source_sha256.strip().lower()
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise ValueError("expected source SHA-256 is invalid")
        if source_sha256 != expected:
            raise ValueError("research dataset SHA-256 does not match source registry")
        source_hash_verified = True

    records: list[NormalizedResearchRecord] = []
    scanned = 0
    rejected = 0
    rejection_reasons: Counter[str] = Counter()
    stopped_at_limit = False
    payloads = _iter_jsonl(path) if dataset_name == "lecardv2" else _iter_json_array(path)
    for payload in payloads:
        if scanned >= max_records:
            stopped_at_limit = True
            break
        scanned += 1
        try:
            record = _normalize_payload(
                payload,
                dataset_name=dataset_name,
                dataset_version=dataset_version,
                max_text_chars=max_text_chars,
            )
        except (KeyError, TypeError, ValueError) as error:
            rejected += 1
            rejection_reasons[str(error) or error.__class__.__name__] += 1
            continue
        records.append(record)

    return ResearchDatasetLoadResult(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        records=tuple(records),
        records_scanned=scanned,
        records_rejected=rejected,
        rejection_reasons=dict(sorted(rejection_reasons.items())),
        stopped_at_limit=stopped_at_limit,
        source_sha256=source_sha256,
        source_size_bytes=source_size_bytes,
        source_hash_verified=source_hash_verified,
        license_review_status=license_review_status,
        permitted_scopes=tuple(dict.fromkeys(permitted_scopes)),
    )


def canonical_case_number(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", "", normalized)
    match = _CASE_NUMBER_PATTERN.search(normalized)
    if match is None:
        return None
    return f"({match.group('year')}){match.group('body')}{int(match.group('serial'))}号"


def _normalize_payload(
    payload: object,
    *,
    dataset_name: str,
    dataset_version: str,
    max_text_chars: int,
) -> NormalizedResearchRecord:
    if not isinstance(payload, dict):
        raise ValueError("research record must be an object")
    if dataset_name == "cail2022-lcr":
        return _normalize_cail2022(payload, dataset_version, max_text_chars)
    if dataset_name == "lecardv2":
        return _normalize_lecard(payload, dataset_version, max_text_chars)
    return _normalize_stard(payload, dataset_version, max_text_chars)


def _normalize_cail2022(
    payload: dict[str, object],
    dataset_version: str,
    max_text_chars: int,
) -> NormalizedResearchRecord:
    path = _required_text(payload.get("path"), "CAIL2022 path")
    ridx = _required_identifier(payload.get("ridx"), "CAIL2022 ridx")
    text = _bounded_text(payload.get("q"), max_text_chars)
    return _record(
        dataset_name="cail2022-lcr",
        dataset_version=dataset_version,
        source_record_id=path,
        source_aliases=(f"ridx:{ridx}",),
        record_kind=ResearchRecordKind.case,
        text=text,
        title=None,
        case_number=None,
        labels=_string_values(payload.get("crime")),
    )


def _normalize_lecard(
    payload: dict[str, object],
    dataset_version: str,
    max_text_chars: int,
) -> NormalizedResearchRecord:
    source_id = _required_identifier(payload.get("id"), "LeCaRDv2 id")
    title = _optional_text(payload.get("title"))
    text = _bounded_text(payload.get("fact"), max_text_chars)
    labels = [*_string_values(payload.get("law"))]
    labels.extend(f"article:{value}" for value in _identifier_values(payload.get("xf")))
    return _record(
        dataset_name="lecardv2",
        dataset_version=dataset_version,
        source_record_id=source_id,
        source_aliases=(),
        record_kind=ResearchRecordKind.case,
        text=text,
        title=title,
        case_number=canonical_case_number(title),
        labels=tuple(labels),
    )


def _normalize_stard(
    payload: dict[str, object],
    dataset_version: str,
    max_text_chars: int,
) -> NormalizedResearchRecord:
    source_id = _required_identifier(payload.get("query_id"), "STARD query_id")
    text = _bounded_text(payload.get("问题"), max_text_chars)
    return _record(
        dataset_name="stard",
        dataset_version=dataset_version,
        source_record_id=source_id,
        source_aliases=(),
        record_kind=ResearchRecordKind.consultation,
        text=text,
        title=None,
        case_number=None,
        labels=_string_values(payload.get("match_name")),
    )


def _record(
    *,
    dataset_name: str,
    dataset_version: str,
    source_record_id: str,
    source_aliases: tuple[str, ...],
    record_kind: ResearchRecordKind,
    text: str,
    title: str | None,
    case_number: str | None,
    labels: tuple[str, ...],
) -> NormalizedResearchRecord:
    normalized_text = _identity_text(text)
    return NormalizedResearchRecord(
        dataset_name=dataset_name,
        dataset_version=dataset_version,
        source_record_id=source_record_id,
        source_aliases=tuple(dict.fromkeys(source_aliases)),
        record_kind=record_kind,
        text=text,
        title=title,
        case_number=case_number,
        labels=tuple(dict.fromkeys(labels)),
        content_hash=sha256(normalized_text.encode("utf-8")).hexdigest(),
    )


def _iter_jsonl(path: Path) -> Iterable[object]:
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            if not raw_line.strip():
                continue
            try:
                yield json.loads(raw_line)
            except json.JSONDecodeError:
                yield None


def _iter_json_array(path: Path) -> Iterable[object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("research dataset must contain a JSON array")
    yield from payload


def _bounded_text(value: object, max_text_chars: int) -> str:
    text = _required_text(value, "research text")
    if len(text) > max_text_chars:
        raise ValueError("research text exceeds max_text_chars")
    return text


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _required_identifier(value: object, label: str) -> str:
    if not isinstance(value, str | int) or isinstance(value, bool):
        raise ValueError(f"{label} is required")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _string_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(text for item in value if isinstance(item, str) and (text := item.strip()))


def _identifier_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        str(item).strip()
        for item in value
        if isinstance(item, str | int) and not isinstance(item, bool) and str(item).strip()
    )


def _identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
