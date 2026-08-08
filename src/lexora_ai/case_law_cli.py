from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from uuid import UUID

from lexora_ai.api.dependencies import get_embedding_gateway, get_session_factory
from lexora_ai.application.case_law_sources import CaseLawSourceService
from lexora_ai.application.case_law_sync import CaseLawSyncService
from lexora_ai.domain import LegalSourceReviewStatus
from lexora_ai.infrastructure.spc_guiding_cases import SpcGuidingCaseConnector


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize official guiding cases")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="download official cases for review")
    sync.add_argument("--manifest", type=Path)
    sync.add_argument("--url", action="append", dest="urls")
    review = commands.add_parser("review", help="approve or reject a downloaded case")
    review.add_argument("source_id", type=UUID)
    review.add_argument("decision", choices=("approve", "reject"))
    embed = commands.add_parser("embed", help="backfill embeddings for approved cases")
    embed.add_argument("--batch-size", type=int, default=64)
    return parser


def _load_urls(path: Path | None) -> list[str]:
    if path is None:
        resource = files("lexora_ai.resources").joinpath("case_law_sources.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(url, str) and url.strip() for url in payload
    ):
        raise ValueError("case-law manifest must be a JSON array of non-empty URLs")
    return [url.strip() for url in payload]


async def _run(args: argparse.Namespace) -> int:
    sources = CaseLawSourceService(get_session_factory(), get_embedding_gateway())
    service = CaseLawSyncService(sources, SpcGuidingCaseConnector())
    if args.command == "sync":
        results = await service.sync(args.urls or _load_urls(args.manifest))
        for result in results:
            print(json.dumps(asdict(result), ensure_ascii=False))
        return 1 if any(result.outcome == "failed" for result in results) else 0
    if args.command == "embed":
        count = await sources.backfill_embeddings(batch_size=args.batch_size)
        print(json.dumps({"embedded_chunks": count}, ensure_ascii=False))
        return 0
    decision = (
        LegalSourceReviewStatus.approved
        if args.decision == "approve"
        else LegalSourceReviewStatus.rejected
    )
    source = await service.review(args.source_id, decision)
    print(
        json.dumps(
            {
                "source_id": str(source.id),
                "case_number": source.case_number,
                "title": source.title,
                "review_status": source.review_status.value,
            },
            ensure_ascii=False,
        )
    )
    return 0


def run() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
