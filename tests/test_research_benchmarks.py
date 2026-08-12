from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from lexora_ai.application.research_benchmark_planning import (
    build_research_benchmark_plan,
)
from lexora_ai.infrastructure.research_benchmark_adapters import (
    load_relevance_judgments,
)
from lexora_ai.infrastructure.research_dataset_adapters import load_research_dataset
from lexora_ai.infrastructure.research_dataset_registry import registered_research_datasets


def test_cail_benchmark_joins_relevance_by_ridx_alias(tmp_path: Path) -> None:
    query_path = _json(
        tmp_path / "queries.json",
        [{"path": "document.json", "ridx": 73305, "q": "案件事实", "crime": ["盗窃罪"]}],
    )
    relevance_path = _json(tmp_path / "labels.json", {"73305": {"9": 3, "10": 0}})
    query_hash = _hash(query_path)
    relevance_hash = _hash(relevance_path)

    queries = load_research_dataset(
        query_path,
        dataset_name="cail2022-lcr",
        dataset_version="fixture",
        expected_source_sha256=query_hash,
    )
    relevance = load_relevance_judgments(
        relevance_path,
        dataset_name="cail2022-lcr",
        expected_source_sha256=relevance_hash,
    )
    plan = build_research_benchmark_plan([(queries, relevance)])

    assert plan.total_queries == 1
    assert plan.judged_queries == 1
    assert plan.orphan_judgment_queries == 0
    assert plan.total_judgments == 2
    assert plan.datasets[0]["grade_distribution"] == {"0": 1, "3": 1}
    assert plan.integrity_ready


def test_lecard_trec_adapter_keeps_zero_grade_and_deduplicates_pairs(tmp_path: Path) -> None:
    relevance_path = tmp_path / "relevance.trec"
    relevance_path.write_text(
        "23\t0\t100\t0\n23\t0\t101\t3\n23\t0\t101\t3\n",
        encoding="utf-8",
    )

    result = load_relevance_judgments(
        relevance_path,
        dataset_name="lecardv2",
        expected_source_sha256=_hash(relevance_path),
    )

    assert [(item.candidate_source_id, item.grade) for item in result.judgments] == [
        ("100", 0),
        ("101", 3),
    ]
    assert result.records_duplicated == 1


def test_relevance_adapter_rejects_conflicting_pair_grades(tmp_path: Path) -> None:
    relevance_path = tmp_path / "relevance.trec"
    relevance_path.write_text("23 0 101 2\n23 0 101 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting grades"):
        load_relevance_judgments(
            relevance_path,
            dataset_name="lecardv2",
            expected_source_sha256=_hash(relevance_path),
        )


def test_stard_queries_embed_binary_relevance_labels(tmp_path: Path) -> None:
    source = _json(
        tmp_path / "queries.json",
        [
            {
                "query_id": 0,
                "问题": "谁可以成为个体工商户？",
                "match_id": [705, 49282],
                "match_name": ["法律一", "法律二"],
            }
        ],
    )
    source_hash = _hash(source)

    queries = load_research_dataset(
        source,
        dataset_name="stard",
        dataset_version="fixture",
        expected_source_sha256=source_hash,
    )
    relevance = load_relevance_judgments(
        source,
        dataset_name="stard",
        expected_source_sha256=source_hash,
    )
    plan = build_research_benchmark_plan([(queries, relevance)])
    rendered = json.dumps(plan.to_dict(), ensure_ascii=False)

    assert plan.judged_queries == 1
    assert plan.total_judgments == 2
    assert plan.distinct_candidates == 2
    assert plan.datasets[0]["grade_distribution"] == {"1": 2}
    assert "谁可以成为个体工商户" not in rendered
    assert not plan.candidate_text_loaded
    assert plan.model_calls == 0


def test_plan_reports_missing_and_orphan_query_labels(tmp_path: Path) -> None:
    query_path = tmp_path / "queries.jsonl"
    query_path.write_text(
        "\n".join(
            json.dumps(
                {"id": query_id, "fact": f"案件事实{query_id}", "law": [], "xf": []},
                ensure_ascii=False,
            )
            for query_id in (1, 2)
        )
        + "\n",
        encoding="utf-8",
    )
    relevance_path = tmp_path / "relevance.trec"
    relevance_path.write_text("1 0 100 2\n3 0 200 1\n", encoding="utf-8")

    queries = load_research_dataset(
        query_path,
        dataset_name="lecardv2",
        dataset_version="fixture",
        expected_source_sha256=_hash(query_path),
    )
    relevance = load_relevance_judgments(
        relevance_path,
        dataset_name="lecardv2",
        expected_source_sha256=_hash(relevance_path),
    )
    plan = build_research_benchmark_plan([(queries, relevance)])

    assert plan.total_queries == 2
    assert plan.judged_queries == 1
    assert plan.queries_without_judgments == 1
    assert plan.orphan_judgment_queries == 1
    assert not plan.integrity_ready
    assert plan.integrity_errors == (
        "lecardv2: queries are missing judgments",
        "lecardv2: judgments reference unknown queries",
    )


def test_registry_separates_cail_normalization_and_benchmark_queries() -> None:
    registration = registered_research_datasets()["cail2022-lcr"]

    assert registration.file_for("queries").name == "stage2-queries"
    assert registration.file_for("benchmark_queries").name == "stage2-benchmark-queries"
    assert (
        registration.file_for("benchmark_relevance_labels").name
        == "stage2-benchmark-relevance-labels"
    )


def _json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
