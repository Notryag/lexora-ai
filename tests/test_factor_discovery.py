from __future__ import annotations

import json
from pathlib import Path

from lexora_ai.application.factor_discovery import build_factor_discovery_plan
from lexora_ai.domain import FactorDiscoveryBudget


def _write_cail_cases(path: Path, count: int = 80) -> None:
    records = []
    for index in range(count):
        months = (index % 4) * 18
        records.append(
            {
                "fact": f"被告人实施盗窃，测试事实编号{index}，涉案金额不同。",
                "meta": {
                    "accusation": ["盗窃" if index < count - 5 else "诈骗"],
                    "term_of_imprisonment": {
                        "imprisonment": months,
                        "life_imprisonment": False,
                        "death_penalty": False,
                    },
                },
            }
        )
    path.write_text(
        "".join(f"{json.dumps(record, ensure_ascii=False)}\n" for record in records),
        encoding="utf-8",
    )


def _budget(**overrides: int) -> FactorDiscoveryBudget:
    values = {
        "discovery_cases": 12,
        "evaluation_cases": 6,
        "max_unique_cases": 18,
        "max_model_calls": 30,
        "max_input_tokens": 300_000,
        "max_output_tokens": 40_000,
        "max_batch_input_tokens": 2_000,
        "max_records_scanned": 100,
        "candidate_pool_multiplier": 3,
        "max_case_chars": 6_000,
    }
    values.update(overrides)
    return FactorDiscoveryBudget(**values)


def _plan(path: Path, budget: FactorDiscoveryBudget | None = None):
    return build_factor_discovery_plan(
        path,
        dataset_format="cail2018",
        dataset_name="test-cail",
        dataset_version="fixture-v1",
        dataset_sha256="a" * 64,
        issue="盗窃罪",
        sampling_seed=42,
        model="test-model",
        budget=budget or _budget(),
    )


def test_plan_uses_bounded_stratified_disjoint_samples(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    _write_cail_cases(path)

    plan = _plan(path)

    discovery = set(plan.selected_discovery_ids)
    evaluation = set(plan.selected_evaluation_ids)
    assert len(discovery) == 12
    assert len(evaluation) == 6
    assert discovery.isdisjoint(evaluation)
    assert len(plan.selected_by_outcome) == 3
    assert plan.records_scanned < 80
    assert plan.stopped_at_pool_limit
    assert plan.dataset_identity_declared
    assert plan.within_budget
    assert plan.execution_ready
    assert plan.dry_run


def test_plan_is_deterministic_and_cache_keys_include_model(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    _write_cail_cases(path)

    first = _plan(path)
    second = _plan(path)
    other_model = build_factor_discovery_plan(
        path,
        dataset_format="cail2018",
        dataset_name="test-cail",
        dataset_version="fixture-v1",
        dataset_sha256="a" * 64,
        issue="盗窃",
        sampling_seed=42,
        model="other-model",
        budget=_budget(),
    )

    assert first.selected_discovery_ids == second.selected_discovery_ids
    assert [batch.cache_key for batch in first.batches] == [
        batch.cache_key for batch in second.batches
    ]
    assert first.batches[0].cache_key != other_model.batches[0].cache_key


def test_plan_reports_token_budget_overflow_without_execution(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    _write_cail_cases(path)

    plan = _plan(path, _budget(max_input_tokens=1_000))

    assert not plan.within_budget
    assert plan.budget_errors == ("estimated input tokens exceed max_input_tokens",)


def test_plan_handles_an_issue_with_no_candidates(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    _write_cail_cases(path)

    plan = build_factor_discovery_plan(
        path,
        dataset_format="cail2018",
        dataset_name="test-cail",
        dataset_version="fixture-v1",
        dataset_sha256=None,
        issue="故意伤害",
        sampling_seed=42,
        model="test-model",
        budget=_budget(),
    )

    assert plan.eligible_candidates == 0
    assert plan.selected_discovery_ids == ()
    assert plan.selected_evaluation_ids == ()
    assert plan.estimated_model_calls == 0
    assert plan.within_budget
    assert not plan.execution_ready
    assert not plan.dataset_identity_declared


def test_loader_deduplicates_identical_case_text(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    record = {
        "fact": "同一份盗窃案件事实",
        "meta": {
            "accusation": ["盗窃"],
            "term_of_imprisonment": {
                "imprisonment": 12,
                "life_imprisonment": False,
                "death_penalty": False,
            },
        },
    }
    path.write_text(
        f"{json.dumps(record, ensure_ascii=False)}\n"
        f"{json.dumps(record, ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    plan = _plan(path)

    assert plan.records_scanned == 2
    assert plan.records_duplicated == 1
    assert plan.eligible_candidates == 1
