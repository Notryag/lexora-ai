from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lexora_ai.application import (
    CaseLawSourceLocator,
    CaseLawSourceService,
    CaseLawSyncService,
)
from lexora_ai.db.models import Base
from lexora_ai.domain import CaseLawSourceCreate, CaseLawStatus


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class CollectionConnector:
    def __init__(self, documents: list[CaseLawSourceCreate]) -> None:
        self.documents = documents
        self.calls: list[CaseLawSourceLocator] = []

    async def fetch(self, locator: CaseLawSourceLocator) -> list[CaseLawSourceCreate]:
        self.calls.append(locator)
        return self.documents


def _typical_case(ordinal: str, title: str, fact: str) -> CaseLawSourceCreate:
    return CaseLawSourceCreate(
        case_number=f"最高法典型案例 2025-01-15 案例{ordinal}",
        title=title,
        issuing_authority="最高人民法院",
        status=CaseLawStatus.active,
        published_on=date(2025, 1, 15),
        source_name="最高人民法院典型案例",
        source_url="https://www.court.gov.cn/zixun/xiangqing/452761.html",
        content=(
            f"案例信息\n{title}\n基本案情\n{fact}\n"
            "裁判结果\n依法作出裁判。\n典型意义\n平衡双方合法权益。"
        ),
    )


@pytest.mark.asyncio
async def test_one_collection_request_creates_selected_cases_without_duplicates(
    session_factory,
) -> None:
    locator = CaseLawSourceLocator(
        source_url="https://www.court.gov.cn/zixun/xiangqing/452761.html",
        case_ordinals=(1, 2),
    )
    connector = CollectionConnector(
        [
            _typical_case("一", "崔某某与陈某某离婚纠纷案", "婚前房屋在婚后加名。"),
            _typical_case("二", "范某某与许某某离婚纠纷案", "父母出资房屋登记双方。"),
        ]
    )
    service = CaseLawSyncService(CaseLawSourceService(session_factory), connector)

    first = await service.sync([locator])
    second = await service.sync([locator])

    assert len(connector.calls) == 2
    assert [result.outcome for result in first] == ["pending_review", "pending_review"]
    assert [result.case_number for result in first] == [
        "最高法典型案例 2025-01-15 案例一",
        "最高法典型案例 2025-01-15 案例二",
    ]
    assert [result.outcome for result in second] == ["unchanged", "unchanged"]
    assert [result.source_id for result in second] == [
        result.source_id for result in first
    ]
