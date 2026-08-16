from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast
from uuid import UUID

from lexora_ai.application.case_law_sources import CaseLawSourceService
from lexora_ai.domain import (
    CaseLawSourceCreate,
    CaseLawSourceDetail,
    CaseLawSourceUpdate,
    LegalSourceReviewStatus,
)


@dataclass(frozen=True, slots=True)
class CaseLawSourceLocator:
    source_url: str
    case_ordinals: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        source_url = self.source_url.strip()
        if not source_url:
            raise ValueError("case-law source URL cannot be blank")
        ordinals = tuple(dict.fromkeys(self.case_ordinals))
        if any(ordinal <= 0 for ordinal in ordinals):
            raise ValueError("case ordinals must be positive")
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "case_ordinals", ordinals)


def parse_case_law_manifest(payload: object) -> list[CaseLawSourceLocator]:
    if not isinstance(payload, list):
        raise ValueError("case-law manifest must be a JSON array")
    locators: list[CaseLawSourceLocator] = []
    for item in payload:
        if isinstance(item, str):
            locators.append(CaseLawSourceLocator(source_url=item))
            continue
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            raise ValueError("case-law manifest entries must be URLs or source objects")
        raw_ordinals = item.get("case_ordinals", [])
        if not isinstance(raw_ordinals, list) or not all(
            isinstance(ordinal, int) and not isinstance(ordinal, bool)
            for ordinal in raw_ordinals
        ):
            raise ValueError("case_ordinals must be an array of integers")
        locators.append(
            CaseLawSourceLocator(
                source_url=cast(str, item["url"]),
                case_ordinals=tuple(raw_ordinals),
            )
        )
    return locators


class CaseLawConnector(Protocol):
    async def fetch(self, locator: CaseLawSourceLocator) -> list[CaseLawSourceCreate]: ...


@dataclass(frozen=True, slots=True)
class CaseLawSyncResult:
    source_url: str
    outcome: str
    source_id: str | None = None
    case_number: str | None = None
    detail: str | None = None


class CaseLawSyncService:
    def __init__(
        self,
        sources: CaseLawSourceService,
        connector: CaseLawConnector,
        *,
        request_interval_seconds: float = 0,
    ) -> None:
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds cannot be negative")
        self._sources = sources
        self._connector = connector
        self._request_interval_seconds = request_interval_seconds

    async def sync(
        self, locators: list[CaseLawSourceLocator]
    ) -> list[CaseLawSyncResult]:
        results: list[CaseLawSyncResult] = []
        existing_versions = {
            (source.source_url, source.content_sha256): source
            for source in await self._sources.list()
        }
        last_request_started_at: float | None = None
        loop = asyncio.get_running_loop()
        for locator in locators:
            try:
                if last_request_started_at is not None:
                    remaining = (
                        self._request_interval_seconds
                        - (loop.time() - last_request_started_at)
                    )
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                last_request_started_at = loop.time()
                documents = await self._connector.fetch(locator)
                for document in documents:
                    content_hash = sha256(document.content.encode()).hexdigest()
                    unchanged = existing_versions.get((document.source_url, content_hash))
                    if unchanged is not None:
                        results.append(
                            CaseLawSyncResult(
                                source_url=locator.source_url,
                                outcome="unchanged",
                                source_id=str(unchanged.id),
                                case_number=document.case_number,
                            )
                        )
                        continue
                    source = await self._sources.create(
                        document.model_copy(
                            update={
                                "review_status": LegalSourceReviewStatus.pending,
                                "verified_at": None,
                            }
                        )
                    )
                    existing_versions[(source.source_url, source.content_sha256)] = source
                    results.append(
                        CaseLawSyncResult(
                            source_url=locator.source_url,
                            outcome="pending_review",
                            source_id=str(source.id),
                            case_number=source.case_number,
                        )
                    )
            except Exception as exc:
                results.append(
                    CaseLawSyncResult(
                        source_url=locator.source_url,
                        outcome="failed",
                        detail=str(exc),
                    )
                )
        return results

    async def review(
        self,
        source_id: UUID,
        review_status: LegalSourceReviewStatus,
    ) -> CaseLawSourceDetail:
        if review_status == LegalSourceReviewStatus.pending:
            raise ValueError("review command accepts only approved or rejected")
        return await self._sources.update(
            source_id,
            CaseLawSourceUpdate(review_status=review_status),
        )
