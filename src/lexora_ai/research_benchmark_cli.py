from __future__ import annotations

import argparse
import json
from pathlib import Path

from lexora_ai.application.research_benchmark_planning import (
    build_research_benchmark_plan,
)
from lexora_ai.infrastructure.research_benchmark_adapters import (
    load_relevance_judgments,
)
from lexora_ai.infrastructure.research_dataset_adapters import load_research_dataset
from lexora_ai.infrastructure.research_dataset_registry import registered_research_datasets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan research retrieval benchmarks")
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        metavar="NAME=QUERY_PATH=RELEVANCE_PATH",
    )
    parser.add_argument("--max-records-per-source", type=int, default=5_000)
    parser.add_argument("--max-text-chars", type=int, default=30_000)
    parser.add_argument("--max-file-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--max-judgments", type=int, default=100_000)
    parser.add_argument("--output", type=Path)
    return parser


def run() -> None:
    args = _parser().parse_args()
    registrations = registered_research_datasets()
    loaded = []
    seen: set[str] = set()
    for raw_dataset in args.dataset:
        name, query_path, relevance_path = _parse_dataset(raw_dataset)
        if name in seen:
            raise ValueError(f"duplicate --dataset: {name}")
        if name not in registrations:
            raise ValueError(f"dataset is not registered: {name}")
        seen.add(name)
        registration = registrations[name]
        query_source = registration.file_for("benchmark_queries")
        relevance_source = registration.file_for("benchmark_relevance_labels")
        queries = load_research_dataset(
            query_path,
            dataset_name=name,
            dataset_version=registration.version,
            max_records=args.max_records_per_source,
            max_text_chars=args.max_text_chars,
            max_file_bytes=args.max_file_bytes,
            expected_source_sha256=query_source.sha256,
            license_review_status=registration.license_review_status,
            permitted_scopes=registration.permitted_scopes,
        )
        relevance = load_relevance_judgments(
            relevance_path,
            dataset_name=name,
            expected_source_sha256=relevance_source.sha256,
            max_file_bytes=args.max_file_bytes,
            max_judgments=args.max_judgments,
        )
        loaded.append((queries, relevance))
    plan = build_research_benchmark_plan(loaded)
    rendered = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    if not plan.integrity_ready:
        raise SystemExit(2)


def _parse_dataset(value: str) -> tuple[str, Path, Path]:
    parts = value.split("=", maxsplit=2)
    if len(parts) != 3 or any(not part.strip() for part in parts):
        raise ValueError("--dataset must use NAME=QUERY_PATH=RELEVANCE_PATH")
    name, raw_query_path, raw_relevance_path = (part.strip() for part in parts)
    query_path = Path(raw_query_path)
    relevance_path = Path(raw_relevance_path)
    if not query_path.is_file():
        raise ValueError(f"query source file does not exist: {query_path}")
    if not relevance_path.is_file():
        raise ValueError(f"relevance source file does not exist: {relevance_path}")
    return name, query_path, relevance_path
