from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from rag_core import RetrievalDocument

from lexora_ai.domain.research_benchmarks import (
    ResearchBenchmarkPlan,
    ResearchRelevanceJudgment,
)
from lexora_ai.infrastructure.sqlite_bm25 import SqliteBm25Index


@dataclass(frozen=True, slots=True)
class ResearchQuery:
    id: str
    text: str


@dataclass(frozen=True, slots=True)
class ResearchRetrievalResult:
    query_id: str
    retrieved_ids: tuple[str, ...]
    first_relevant_rank: int | None
    relevant_retrieved: int
    relevant_total: int


def build_and_evaluate_bm25(
    *,
    plan: ResearchBenchmarkPlan,
    dataset_name: str,
    corpus_identity: str,
    documents: Iterable[RetrievalDocument],
    queries: Iterable[ResearchQuery],
    judgments: Iterable[ResearchRelevanceJudgment],
    index_path: Path,
    top_k: int = 10,
    relevant_grade: int = 1,
) -> dict[str, object]:
    if not plan.evaluation_ready:
        raise ValueError("research benchmark is not approved and ready for evaluation")
    if top_k <= 0 or top_k > 1_000:
        raise ValueError("top_k must be between 1 and 1000")
    if not 0 <= relevant_grade <= 3:
        raise ValueError("relevant_grade must be between 0 and 3")

    relevant_by_query: dict[str, set[str]] = {}
    for judgment in judgments:
        if judgment.dataset_name != dataset_name or judgment.grade < relevant_grade:
            continue
        relevant_by_query.setdefault(judgment.query_source_id, set()).add(
            judgment.candidate_source_id
        )
    query_items = tuple(queries)
    if not query_items:
        raise ValueError("research benchmark has no queries")
    if len({query.id for query in query_items}) != len(query_items):
        raise ValueError("research benchmark query IDs are not unique")
    if any(query.id not in relevant_by_query for query in query_items):
        raise ValueError("research benchmark query has no relevant judgments")

    index = SqliteBm25Index(index_path)
    index_result = index.build(documents, corpus_identity=corpus_identity)
    results: list[ResearchRetrievalResult] = []
    for query in query_items:
        relevant = relevant_by_query[query.id]
        retrieved = index.search(query.text, top_k=top_k)
        retrieved_ids = tuple(item.document_id for item in retrieved)
        ranks = [rank for rank, item in enumerate(retrieved_ids, start=1) if item in relevant]
        results.append(
            ResearchRetrievalResult(
                query_id=query.id,
                retrieved_ids=retrieved_ids,
                first_relevant_rank=min(ranks) if ranks else None,
                relevant_retrieved=len(ranks),
                relevant_total=len(relevant),
            )
        )
    query_count = len(results)
    return {
        "dataset_name": dataset_name,
        "retriever": "sqlite_fts5_bm25_cjk_2_3gram",
        "corpus_identity": corpus_identity,
        "index_reused": index_result.reused,
        "documents": index_result.document_count,
        "queries": query_count,
        "top_k": top_k,
        "relevant_grade": relevant_grade,
        "hit_rate_at_k": round(
            sum(result.first_relevant_rank is not None for result in results) / query_count,
            4,
        ),
        "macro_recall_at_k": round(
            sum(result.relevant_retrieved / result.relevant_total for result in results)
            / query_count,
            4,
        ),
        "mrr_at_k": round(
            sum(
                1 / result.first_relevant_rank
                for result in results
                if result.first_relevant_rank is not None
            )
            / query_count,
            4,
        ),
        "results": [asdict(result) for result in results],
        "model_calls": 0,
    }


def load_stard_documents(path: Path) -> Iterable[RetrievalDocument]:
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            if not raw_line.strip():
                continue
            payload = json.loads(raw_line)
            if not isinstance(payload, dict):
                raise ValueError("STARD candidate record must be an object")
            candidate_id = payload.get("id")
            name = payload.get("name")
            content = payload.get("content")
            if not isinstance(candidate_id, str | int) or isinstance(candidate_id, bool):
                raise ValueError("STARD candidate ID is invalid")
            if not isinstance(name, str) or not isinstance(content, str):
                raise ValueError("STARD candidate text is invalid")
            yield RetrievalDocument(
                id=str(candidate_id),
                content=f"{name}\n{content}",
            )
