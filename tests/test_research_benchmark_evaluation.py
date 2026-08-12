from __future__ import annotations

from pathlib import Path

import pytest
from rag_core import RetrievalDocument

from lexora_ai.domain.research_benchmarks import (
    ResearchBenchmarkPlan,
    ResearchRelevanceJudgment,
)
from lexora_ai.evaluation.research_benchmark import (
    ResearchQuery,
    build_and_evaluate_bm25,
)


def test_bm25_evaluation_reports_strict_retrieval_metrics(tmp_path: Path) -> None:
    report = build_and_evaluate_bm25(
        plan=_ready_plan(),
        dataset_name="fixture",
        corpus_identity="sha256:fixture",
        documents=[
            RetrievalDocument(id="7", content="合同违约损失赔偿"),
            RetrievalDocument(id="8", content="合同解除返还财产"),
            RetrievalDocument(id="9", content="婚姻登记与离婚"),
        ],
        queries=[ResearchQuery(id="q1", text="合同违约怎么赔偿")],
        judgments=[
            ResearchRelevanceJudgment("fixture", "q1", "7", 2),
            ResearchRelevanceJudgment("fixture", "q1", "8", 1),
        ],
        index_path=tmp_path / "bm25.sqlite3",
        top_k=1,
    )

    assert report["hit_rate_at_k"] == 1.0
    assert report["macro_recall_at_k"] == 0.5
    assert report["mrr_at_k"] == 1.0
    assert report["model_calls"] == 0


def test_bm25_evaluation_refuses_an_unapproved_plan(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not approved and ready"):
        build_and_evaluate_bm25(
            plan=_ready_plan(evaluation_ready=False),
            dataset_name="fixture",
            corpus_identity="fixture",
            documents=[RetrievalDocument(id="7", content="合同违约")],
            queries=[ResearchQuery(id="q1", text="合同违约")],
            judgments=[ResearchRelevanceJudgment("fixture", "q1", "7", 1)],
            index_path=tmp_path / "bm25.sqlite3",
        )

    assert not (tmp_path / "bm25.sqlite3").exists()


def _ready_plan(*, evaluation_ready: bool = True) -> ResearchBenchmarkPlan:
    return ResearchBenchmarkPlan(
        benchmark_version="fixture",
        plan_identity="fixture",
        datasets=(),
        total_queries=1,
        judged_queries=1,
        queries_without_judgments=0,
        orphan_judgment_queries=0,
        total_judgments=1,
        distinct_candidates=1,
        integrity_ready=True,
        integrity_errors=(),
        evaluation_ready=evaluation_ready,
        readiness_errors=() if evaluation_ready else ("license pending",),
    )
