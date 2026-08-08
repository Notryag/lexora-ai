from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from lexora_ai.case_law_context import rank_case_law, split_case_law
from lexora_ai.domain import CaseLawChunk
from lexora_ai.infrastructure import SpcGuidingCaseConnector

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[3] / "evaluation/case_law_retrieval.jsonl"


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


async def evaluate(cases_path: Path = DEFAULT_CASES_PATH) -> dict[str, object]:
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


def _load_cases(path: Path) -> list[EvaluationCase]:
    return [
        EvaluationCase(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _load_corpus() -> list[CaseLawChunk]:
    urls = json.loads(
        files("lexora_ai.resources").joinpath("case_law_sources.json").read_text(encoding="utf-8")
    )
    connector = SpcGuidingCaseConnector()
    result: list[CaseLawChunk] = []
    for source_url in urls:
        source = await connector.fetch(source_url)
        source_id = uuid5(NAMESPACE_URL, source.source_url)
        for index, draft in enumerate(
            split_case_law(source_id, source.title, source.content),
            start=1,
        ):
            result.append(
                CaseLawChunk(
                    id=uuid5(source_id, str(index)),
                    source_id=source_id,
                    reference=f"C{source_id.hex}:S{index}",
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
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate(args.cases))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
