from __future__ import annotations

import argparse
import json
from pathlib import Path

from lexora_ai.application.research_dataset_normalization import (
    build_research_normalization_plan,
)
from lexora_ai.infrastructure.research_dataset_adapters import load_research_dataset
from lexora_ai.infrastructure.research_dataset_registry import registered_research_datasets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run research dataset normalization and dedupe"
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="DATASET=PATH",
        help="repeat for cail2022-lcr, lecardv2, and stard",
    )
    parser.add_argument("--max-records-per-source", type=int, default=5_000)
    parser.add_argument("--max-text-chars", type=int, default=30_000)
    parser.add_argument("--max-file-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--duplicate-group-limit", type=int, default=20)
    parser.add_argument("--output", type=Path)
    return parser


def run() -> None:
    args = _parser().parse_args()
    registrations = registered_research_datasets()
    loaded = []
    seen_names: set[str] = set()
    for raw_source in args.source:
        name, path = _parse_source(raw_source)
        if name in seen_names:
            raise ValueError(f"duplicate --source dataset: {name}")
        if name not in registrations:
            raise ValueError(f"dataset is not registered: {name}")
        registration = registrations[name]
        query_source = registration.file_for("queries")
        seen_names.add(name)
        loaded.append(
            load_research_dataset(
                path,
                dataset_name=name,
                dataset_version=registration.version,
                max_records=args.max_records_per_source,
                max_text_chars=args.max_text_chars,
                max_file_bytes=args.max_file_bytes,
                expected_source_sha256=query_source.sha256,
                license_review_status=registration.license_review_status,
                permitted_scopes=registration.permitted_scopes,
            )
        )
    plan = build_research_normalization_plan(
        loaded,
        duplicate_group_limit=args.duplicate_group_limit,
    )
    rendered = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


def _parse_source(value: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise ValueError("--source must use DATASET=PATH")
    path = Path(raw_path.strip())
    if not path.is_file():
        raise ValueError(f"dataset source file does not exist: {path}")
    return name.strip(), path
