from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from lexora_ai.application.legal_sources import LegalSourceService
from lexora_ai.domain import (
    LegalSourceCreate,
    LegalSourceDetail,
    LegalSourceReviewStatus,
    LegalSourceUpdate,
)


class LegalSourceConnector(Protocol):
    async def fetch(self, title: str) -> LegalSourceCreate: ...


@dataclass(frozen=True, slots=True)
class LegalSourceSyncResult:
    title: str
    outcome: str
    source_id: str | None = None
    detail: str | None = None


class LegalSourceSyncService:
    def __init__(
        self,
        sources: LegalSourceService,
        connector: LegalSourceConnector,
    ) -> None:
        self._sources = sources
        self._connector = connector

    async def sync(self, titles: list[str]) -> list[LegalSourceSyncResult]:
        results: list[LegalSourceSyncResult] = []
        existing_versions = {
            (source.source_url, source.content_sha256): source
            for source in await self._sources.list()
        }
        for title in titles:
            try:
                document = await self._connector.fetch(title)
                content_hash = sha256(document.content.encode()).hexdigest()
                unchanged = existing_versions.get(
                    (document.source_url, content_hash),
                )
                if unchanged is not None:
                    results.append(
                        LegalSourceSyncResult(
                            title=title,
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
                    LegalSourceSyncResult(
                        title=title,
                        outcome="pending_review",
                        source_id=str(source.id),
                    )
                )
            except Exception as exc:
                results.append(
                    LegalSourceSyncResult(
                        title=title,
                        outcome="failed",
                        detail=str(exc),
                    )
                )
        return results

    async def review(
        self,
        source_id: UUID,
        review_status: LegalSourceReviewStatus,
    ) -> LegalSourceDetail:
        if review_status == LegalSourceReviewStatus.pending:
            raise ValueError("review command accepts only approved or rejected")
        return await self._sources.update(
            source_id,
            LegalSourceUpdate(review_status=review_status),
        )
