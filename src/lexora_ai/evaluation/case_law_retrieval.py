from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from uuid import uuid5

from lexora_ai.api.dependencies import get_session_factory
from lexora_ai.application.case_law_sources import CaseLawSourceService
from lexora_ai.case_law_context import rank_case_law, split_case_law
from lexora_ai.domain import CaseLawChunk, CaseLawStatus, LegalSourceReviewStatus

DEFAULT_CASES_RESOURCE = "case_law_retrieval.jsonl"


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    query: str
    expected_case_number: str
    expected_evidence: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    expected: str
    retrieved: list[str]
    relevant_rank: int | None


async def evaluate(cases_path: Path | None = None) -> dict[str, object]:
    cases = _load_cases(cases_path)
    chunks = await _load_corpus()
    _validate_evidence(cases, chunks)
    results: list[CaseResult] = []
    for case in cases:
        retrieved = rank_case_law(
            case.query,
            chunks,
            query_embedding=None,
            embedding_model=None,
            top_k=5,
        )
        source_order = list(dict.fromkeys(chunk.case_number for chunk in retrieved))
        rank = (
            source_order.index(case.expected_case_number) + 1
            if case.expected_case_number in source_order
            else None
        )
        results.append(
            CaseResult(
                id=case.id,
                expected=case.expected_case_number,
                retrieved=source_order,
                relevant_rank=rank,
            )
        )
    count = len(results)
    return {
        "retriever": "lexical_ngram",
        "corpus_sources": len({chunk.source_id for chunk in chunks}),
        "corpus_chunks": len(chunks),
        "cases": count,
        "recall_at_1": _recall_at(results, 1),
        "recall_at_3": _recall_at(results, 3),
        "recall_at_5": _recall_at(results, 5),
        "mrr_at_5": round(
            sum(1 / result.relevant_rank for result in results if result.relevant_rank) / count,
            4,
        ),
        "failures": [asdict(result) for result in results if result.relevant_rank is None],
        "results": [asdict(result) for result in results],
    }


def _load_cases(path: Path | None) -> list[EvaluationCase]:
    text = (
        path.read_text(encoding="utf-8")
        if path is not None
        else files("lexora_ai.resources")
        .joinpath(DEFAULT_CASES_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return [
        EvaluationCase(**json.loads(line))
        for line in text.splitlines()
        if line.strip()
    ]


async def _load_corpus() -> list[CaseLawChunk]:
    service = CaseLawSourceService(get_session_factory())
    summaries = [
        source
        for source in await service.list()
        if source.status == CaseLawStatus.active
        and source.review_status == LegalSourceReviewStatus.approved
    ]
    result: list[CaseLawChunk] = []
    for summary in summaries:
        source = await service.get(summary.id)
        for index, draft in enumerate(
            split_case_law(source.id, source.title, source.content),
            start=1,
        ):
            result.append(
                CaseLawChunk(
                    id=uuid5(source.id, str(index)),
                    source_id=source.id,
                    reference=f"C{source.id.hex}:S{index}",
                    section_label=draft.section_label,
                    case_number=source.case_number,
                    title=source.title,
                    keywords=source.keywords,
                    issuing_authority=source.issuing_authority,
                    source_url=source.source_url,
                    published_on=source.published_on,
                    content=draft.content,
                )
            )
    return result


def _validate_evidence(cases: list[EvaluationCase], chunks: list[CaseLawChunk]) -> None:
    for case in cases:
        source_text = "\n".join(
            chunk.content for chunk in chunks if chunk.case_number == case.expected_case_number
        )
        if case.expected_evidence not in source_text:
            raise ValueError(
                f"{case.id}: evidence is absent from {case.expected_case_number}"
            )


def _recall_at(results: list[CaseResult], k: int) -> float:
    return round(
        sum(result.relevant_rank is not None and result.relevant_rank <= k for result in results)
        / len(results),
        4,
    )


def run() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Lexora case-law retrieval")
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.cases))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
