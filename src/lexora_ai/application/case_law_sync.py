from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from lexora_ai.application.case_law_sources import CaseLawSourceService
from lexora_ai.domain import (
    CaseLawSourceCreate,
    CaseLawSourceDetail,
    CaseLawSourceUpdate,
    LegalSourceReviewStatus,
)


class CaseLawConnector(Protocol):
    async def fetch(self, source_url: str) -> CaseLawSourceCreate: ...


@dataclass(frozen=True, slots=True)
class CaseLawSyncResult:
    source_url: str
    outcome: str
    source_id: str | None = None
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

    async def sync(self, source_urls: list[str]) -> list[CaseLawSyncResult]:
        results: list[CaseLawSyncResult] = []
        existing_versions = {
            (source.source_url, source.content_sha256): source
            for source in await self._sources.list()
        }
        last_request_started_at: float | None = None
        loop = asyncio.get_running_loop()
        for source_url in source_urls:
            try:
                if last_request_started_at is not None:
                    remaining = (
                        self._request_interval_seconds
                        - (loop.time() - last_request_started_at)
                    )
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                last_request_started_at = loop.time()
                document = await self._connector.fetch(source_url)
                content_hash = sha256(document.content.encode()).hexdigest()
                unchanged = existing_versions.get((document.source_url, content_hash))
                if unchanged is not None:
                    results.append(
                        CaseLawSyncResult(
                            source_url=source_url,
                            outcome="unchanged",
                            source_id=str(unchanged.id),
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
                        source_url=source_url,
                        outcome="pending_review",
                        source_id=str(source.id),
                    )
                )
            except Exception as exc:
                results.append(
                    CaseLawSyncResult(
                        source_url=source_url,
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
