from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable

from lexora_ai.domain.research_datasets import (
    NormalizedResearchRecord,
    ResearchDatasetLoadResult,
    ResearchDuplicateGroup,
    ResearchNormalizationPlan,
    ResearchRecordKind,
)


def build_research_normalization_plan(
    loaded_sources: list[ResearchDatasetLoadResult],
    *,
    duplicate_group_limit: int = 20,
) -> ResearchNormalizationPlan:
    if duplicate_group_limit <= 0:
        raise ValueError("duplicate_group_limit must be positive")
    records = [record for source in loaded_sources for record in source.records]
    seen_source_keys: set[tuple[str, str]] = set()
    seen_case_numbers: set[str] = set()
    seen_content_hashes: set[tuple[ResearchRecordKind, str]] = set()
    duplicate_reasons: Counter[str] = Counter()
    unique_records = 0

    for record in records:
        source_keys = _source_keys(record)
        if any(key in seen_source_keys for key in source_keys):
            duplicate_reasons["source_id"] += 1
        elif record.case_number and record.case_number in seen_case_numbers:
            duplicate_reasons["case_number"] += 1
        elif (record.record_kind, record.content_hash) in seen_content_hashes:
            duplicate_reasons["content_hash"] += 1
        else:
            unique_records += 1
        seen_source_keys.update(source_keys)
        if record.case_number:
            seen_case_numbers.add(record.case_number)
        seen_content_hashes.add((record.record_kind, record.content_hash))

    source_summaries = tuple(_source_summary(source) for source in loaded_sources)
    duplicate_records = sum(duplicate_reasons.values())
    return ResearchNormalizationPlan(
        sources=source_summaries,
        total_records=len(records),
        unique_records=unique_records,
        duplicate_records=duplicate_records,
        duplicate_source_ids=duplicate_reasons["source_id"],
        duplicate_case_numbers=duplicate_reasons["case_number"],
        duplicate_content_hashes=duplicate_reasons["content_hash"],
        case_records_without_case_number=sum(
            record.record_kind == ResearchRecordKind.case and not record.case_number
            for record in records
        ),
        consultation_records=sum(
            record.record_kind == ResearchRecordKind.consultation for record in records
        ),
        cross_source_case_number_groups=_cross_source_groups(
            records,
            identity=lambda record: record.case_number,
            limit=duplicate_group_limit,
            require_distinct_content=True,
        ),
        cross_source_content_groups=_cross_source_groups(
            records,
            identity=lambda record: f"{record.record_kind.value}:{record.content_hash}",
            limit=duplicate_group_limit,
        ),
    )


def _source_keys(record: NormalizedResearchRecord) -> set[tuple[str, str]]:
    return {
        (record.dataset_name, source_id)
        for source_id in (record.source_record_id, *record.source_aliases)
    }


def _source_summary(source: ResearchDatasetLoadResult) -> dict[str, object]:
    kinds = Counter(record.record_kind.value for record in source.records)
    return {
        "dataset_name": source.dataset_name,
        "dataset_version": source.dataset_version,
        "records_scanned": source.records_scanned,
        "records_normalized": len(source.records),
        "records_rejected": source.records_rejected,
        "rejection_reasons": source.rejection_reasons,
        "records_with_case_number": sum(bool(record.case_number) for record in source.records),
        "record_kinds": dict(sorted(kinds.items())),
        "stopped_at_limit": source.stopped_at_limit,
    }


def _cross_source_groups(
    records: list[NormalizedResearchRecord],
    *,
    identity: Callable[[NormalizedResearchRecord], str | None],
    limit: int,
    require_distinct_content: bool = False,
) -> tuple[ResearchDuplicateGroup, ...]:
    grouped: dict[str, list[NormalizedResearchRecord]] = defaultdict(list)
    for record in records:
        key = identity(record)
        if key:
            grouped[key].append(record)
    results: list[ResearchDuplicateGroup] = []
    for key, items in sorted(grouped.items()):
        if len({item.dataset_name for item in items}) < 2:
            continue
        if require_distinct_content and len({item.content_hash for item in items}) < 2:
            continue
        results.append(
            ResearchDuplicateGroup(
                identity=key,
                references=tuple(item.reference for item in items),
            )
        )
        if len(results) == limit:
            break
    return tuple(results)
