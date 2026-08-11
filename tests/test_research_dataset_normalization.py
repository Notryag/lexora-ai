from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from lexora_ai.application.research_dataset_normalization import (
    build_research_normalization_plan,
)
from lexora_ai.domain.research_datasets import (
    NormalizedResearchRecord,
    ResearchDatasetLoadResult,
    ResearchRecordKind,
)
from lexora_ai.infrastructure.research_dataset_adapters import (
    canonical_case_number,
    load_research_dataset,
)


def test_adapters_normalize_all_registered_source_shapes(tmp_path: Path) -> None:
    cail = tmp_path / "cail.json"
    cail.write_text(
        json.dumps(
            [
                {
                    "path": "case-a.json",
                    "ridx": 17,
                    "q": "被告人实施盗窃并退赃。",
                    "crime": ["盗窃罪"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lecard = tmp_path / "lecard.jsonl"
    lecard.write_text(
        json.dumps(
            {
                "id": 23,
                "title": "某法院刑事判决书（2020）京0101刑初001号",
                "fact": "被告人入户盗窃。",
                "law": ["盗窃罪"],
                "xf": [264],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    stard = tmp_path / "stard.json"
    stard.write_text(
        json.dumps(
            [
                {
                    "query_id": 5,
                    "问题": "分居会自动离婚吗？",
                    "match_name": ["中华人民共和国民法典第一千零七十九条"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cail_result = load_research_dataset(
        cail,
        dataset_name="cail2022-lcr",
        dataset_version="fixture",
    )
    lecard_result = load_research_dataset(
        lecard,
        dataset_name="lecardv2",
        dataset_version="fixture",
    )
    stard_result = load_research_dataset(
        stard,
        dataset_name="stard",
        dataset_version="fixture",
    )

    assert cail_result.records[0].source_record_id == "case-a.json"
    assert cail_result.records[0].source_aliases == ("ridx:17",)
    assert lecard_result.records[0].case_number == "(2020)京0101刑初1号"
    assert lecard_result.records[0].labels == ("盗窃罪", "article:264")
    assert stard_result.records[0].record_kind == ResearchRecordKind.consultation
    assert stard_result.records[0].labels == (
        "中华人民共和国民法典第一千零七十九条",
    )


def test_case_number_normalization_handles_full_width_parentheses_and_spaces() -> None:
    assert (
        canonical_case_number("判决书 （ 2020 ） 京0101刑初第001号")
        == "(2020)京0101刑初1号"
    )


def test_lecard_adapter_keeps_case_with_facts_but_no_title(tmp_path: Path) -> None:
    source = tmp_path / "lecard.jsonl"
    source.write_text(
        json.dumps(
            {"id": 580, "title": "", "fact": "案件事实完整。", "law": [], "xf": []},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = load_research_dataset(
        source,
        dataset_name="lecardv2",
        dataset_version="fixture",
    )

    assert len(result.records) == 1
    assert result.records_rejected == 0
    assert result.records[0].title is None
    assert result.records[0].case_number is None


def test_adapter_rejects_source_over_file_size_limit(tmp_path: Path) -> None:
    source = tmp_path / "stard.json"
    source.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="exceeds max_file_bytes"):
        load_research_dataset(
            source,
            dataset_name="stard",
            dataset_version="fixture",
            max_file_bytes=1,
        )


def test_plan_deduplicates_cross_source_case_versions_and_exact_content() -> None:
    case_number = "(2020)京0101刑初1号"
    first = _record("cail2022-lcr", "source-a", "版本一", case_number=case_number)
    second = _record("lecardv2", "source-b", "版本二", case_number=case_number)
    third = _record("lecardv2", "source-c", "完全相同")
    fourth = _record("cail2022-lcr", "source-d", "完全相同")
    consultation = _record(
        "stard",
        "source-e",
        "完全相同",
        kind=ResearchRecordKind.consultation,
    )

    plan = build_research_normalization_plan(
        [
            _loaded("cail2022-lcr", first, fourth),
            _loaded("lecardv2", second, third),
            _loaded("stard", consultation),
        ]
    )

    assert plan.total_records == 5
    assert plan.unique_records == 3
    assert plan.duplicate_case_numbers == 1
    assert plan.duplicate_content_hashes == 1
    assert plan.consultation_records == 1
    assert plan.cross_source_case_number_groups[0].references == (
        "cail2022-lcr:source-a",
        "lecardv2:source-b",
    )
    assert plan.cross_source_content_groups[0].references == (
        "cail2022-lcr:source-d",
        "lecardv2:source-c",
    )


def test_plan_deduplicates_repeated_source_alias() -> None:
    first = _record("cail2022-lcr", "path-a", "事实一", aliases=("ridx:7",))
    second = _record("cail2022-lcr", "path-b", "事实二", aliases=("ridx:7",))

    plan = build_research_normalization_plan([_loaded("cail2022-lcr", first, second)])

    assert plan.unique_records == 1
    assert plan.duplicate_source_ids == 1


def test_same_case_and_content_is_not_reported_as_a_text_version() -> None:
    case_number = "(2020)京0101刑初1号"
    first = _record("cail2022-lcr", "source-a", "相同文本", case_number=case_number)
    second = _record("lecardv2", "source-b", "相同文本", case_number=case_number)

    plan = build_research_normalization_plan(
        [_loaded("cail2022-lcr", first), _loaded("lecardv2", second)]
    )

    assert plan.duplicate_case_numbers == 1
    assert plan.cross_source_case_number_groups == ()
    assert len(plan.cross_source_content_groups) == 1


def _record(
    dataset: str,
    source_id: str,
    text: str,
    *,
    case_number: str | None = None,
    kind: ResearchRecordKind = ResearchRecordKind.case,
    aliases: tuple[str, ...] = (),
) -> NormalizedResearchRecord:
    return NormalizedResearchRecord(
        dataset_name=dataset,
        dataset_version="fixture",
        source_record_id=source_id,
        source_aliases=aliases,
        record_kind=kind,
        text=text,
        title=None,
        case_number=case_number,
        labels=(),
        content_hash=sha256(text.encode()).hexdigest(),
    )


def _loaded(
    dataset: str,
    *records: NormalizedResearchRecord,
) -> ResearchDatasetLoadResult:
    return ResearchDatasetLoadResult(
        dataset_name=dataset,
        dataset_version="fixture",
        records=records,
        records_scanned=len(records),
        records_rejected=0,
        rejection_reasons={},
        stopped_at_limit=False,
    )
