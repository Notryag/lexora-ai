from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from uuid import UUID

from lexora_ai.api.dependencies import get_embedding_gateway, get_session_factory
from lexora_ai.application.legal_source_sync import LegalSourceSyncService
from lexora_ai.application.legal_sources import LegalSourceService
from lexora_ai.config import get_settings
from lexora_ai.domain import LegalSourceReviewStatus
from lexora_ai.infrastructure.lvyan_lawtext import LvyanLawTextConnector


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize reviewed official legal sources")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="import lvyan-lawtext versions for review")
    sync.add_argument("--manifest", type=Path)
    sync.add_argument("--title", action="append", dest="titles")
    sync.add_argument("--all-current", action="store_true")
    sync.add_argument("--repository", type=Path)
    review = commands.add_parser("review", help="approve or reject a downloaded version")
    review.add_argument("source_id", type=UUID)
    review.add_argument("decision", choices=("approve", "reject"))
    embed = commands.add_parser("embed", help="backfill embeddings for approved current sources")
    embed.add_argument("--batch-size", type=int, default=64)
    return parser


def _load_titles(path: Path | None) -> list[str]:
    if path is None:
        resource = files("lexora_ai.resources").joinpath("legal_sources.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(title, str) and title.strip() for title in payload
    ):
        raise ValueError("legal source manifest must be a JSON array of non-empty titles")
    return [title.strip() for title in payload]


async def _run(args: argparse.Namespace) -> int:
    sources = LegalSourceService(get_session_factory(), get_embedding_gateway())
    repository = getattr(args, "repository", None) or get_settings().legal_source_repository_path
    connector = LvyanLawTextConnector(repository)
    service = LegalSourceSyncService(sources, connector)
    if args.command == "sync":
        if args.all_current and (args.titles or args.manifest):
            raise ValueError("--all-current cannot be combined with --title or --manifest")
        titles = connector.current_titles() if args.all_current else args.titles
        results = await service.sync(titles or _load_titles(args.manifest))
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
                "title": source.title,
                "review_status": source.review_status.value,
            },
            ensure_ascii=False,
        )
    )
    return 0


def run() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
