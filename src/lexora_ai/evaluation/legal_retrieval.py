from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from lexora_ai.domain import LegalKnowledgeChunk
from lexora_ai.infrastructure import LvyanLawTextConnector
from lexora_ai.legal_context import rank_legal_knowledge, split_legal_source

DEFAULT_CASES_PATH = Path(__file__).resolve().parents[3] / "evaluation/legal_retrieval.jsonl"


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    query: str
    expected_title: str
    expected_article: str
    expected_evidence: str


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    expected: str
    retrieved: list[str]
    relevant_rank: int | None


async def evaluate(
    repository_path: Path,
    cases_path: Path = DEFAULT_CASES_PATH,
) -> dict[str, object]:
    cases = _load_cases(cases_path)
    chunks = await _load_corpus(repository_path, cases)
    _validate_evidence(cases, chunks)

    results: list[CaseResult] = []
    for case in cases:
        retrieved = rank_legal_knowledge(
            case.query,
            chunks,
            query_embedding=None,
            embedding_model=None,
            top_k=5,
        )
        rank = next(
            (
                index
                for index, chunk in enumerate(retrieved, start=1)
                if chunk.title == case.expected_title
                and chunk.article_label == case.expected_article
            ),
            None,
        )
        results.append(
            CaseResult(
                id=case.id,
                expected=f"{case.expected_title} {case.expected_article}",
                retrieved=[f"{chunk.title} {chunk.article_label or ''}".strip() for chunk in retrieved],
                relevant_rank=rank,
            )
        )

    case_count = len(results)
    return {
        "retriever": "exact_article + lexical_ngram + reciprocal_rank_fusion",
        "corpus_sources": len({chunk.source_id for chunk in chunks}),
        "corpus_chunks": len(chunks),
        "cases": case_count,
        "recall_at_1": _recall_at(results, 1),
        "recall_at_3": _recall_at(results, 3),
        "recall_at_5": _recall_at(results, 5),
        "mrr_at_5": round(
            sum(1 / result.relevant_rank for result in results if result.relevant_rank) / case_count,
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


async def _load_corpus(
    repository_path: Path,
    cases: list[EvaluationCase],
) -> list[LegalKnowledgeChunk]:
    connector = LvyanLawTextConnector(repository_path)
    result: list[LegalKnowledgeChunk] = []
    for title in dict.fromkeys(case.expected_title for case in cases):
        source = await connector.fetch(title)
        source_id = uuid5(NAMESPACE_URL, source.source_url)
        for index, draft in enumerate(
            split_legal_source(source_id, source.title, source.content),
            start=1,
        ):
            result.append(
                LegalKnowledgeChunk(
                    id=uuid5(source_id, str(index)),
                    source_id=source_id,
                    reference=f"{source_id}:{index}",
                    article_label=draft.article_label,
                    heading_path=draft.heading_path,
                    title=source.title,
                    issuing_authority=source.issuing_authority,
                    source_url=str(source.source_url),
                    status=source.status,
                    content=draft.content,
                )
            )
    return result


def _validate_evidence(
    cases: list[EvaluationCase],
    chunks: list[LegalKnowledgeChunk],
) -> None:
    for case in cases:
        source_text = "\n".join(
            chunk.content
            for chunk in chunks
            if chunk.title == case.expected_title
            and chunk.article_label == case.expected_article
        )
        if case.expected_evidence not in source_text:
            raise ValueError(
                f"{case.id}: evidence is absent from "
                f"{case.expected_title} {case.expected_article}"
            )


def _recall_at(results: list[CaseResult], k: int) -> float:
    return round(
        sum(result.relevant_rank is not None and result.relevant_rank <= k for result in results)
        / len(results),
        4,
    )


def run() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Lexora legal retrieval")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = asyncio.run(evaluate(args.repository, args.cases))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
