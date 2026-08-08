from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lexora_ai.application import LegalSourceService, LegalSourceSyncService
from lexora_ai.db.models import Base
from lexora_ai.domain import LegalSourceReviewStatus, LegalSourceStatus
from lexora_ai.infrastructure import DatabaseLegalKnowledgePort, LvyanLawTextConnector
from lexora_ai.legal_context import split_legal_source


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


def _write_law(
    repository: Path,
    *,
    source_id: str,
    publication_date: str,
    status: str,
    article_text: str,
) -> None:
    target = repository / "content" / "法律" / f"{source_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""---
id: {source_id}
title: 中华人民共和国劳动法
LinkTitle: 中华人民共和国劳动法（{publication_date[:4]}）
author: 全国人民代表大会常务委员会
publication_date: '{publication_date}'
effective_date: '{publication_date}'
status: {status}
group: 法律
urls:
  - https://flk.npc.gov.cn/detail?id={source_id}
---

**中华人民共和国劳动法**

## 第一章 总则

- **第一条**　{article_text}

- **第二条**　用人单位应当依法支付劳动报酬。
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_lvyan_connector_selects_current_version_and_normalizes_articles(tmp_path) -> None:
    _write_law(
        tmp_path,
        source_id="old-version",
        publication_date="2009-08-27",
        status="已修改",
        article_text="旧版内容。",
    )
    _write_law(
        tmp_path,
        source_id="current-version",
        publication_date="2018-12-29",
        status="有效",
        article_text="保护劳动者合法权益。",
    )

    source = await LvyanLawTextConnector(tmp_path).fetch("中华人民共和国劳动法")
    chunks = split_legal_source(UUID(int=1), source.title, source.content)

    assert source.status == LegalSourceStatus.effective
    assert source.review_status == LegalSourceReviewStatus.pending
    assert source.source_url.endswith("id=current-version")
    assert [chunk.article_label for chunk in chunks] == ["第一条", "第二条"]
    assert chunks[0].heading_path == ("第一章 总则",)
    assert chunks[0].content == "第一条 保护劳动者合法权益。"


@pytest.mark.asyncio
async def test_synced_source_requires_review_before_retrieval(
    session_factory,
    tmp_path,
) -> None:
    _write_law(
        tmp_path,
        source_id="current-version",
        publication_date="2018-12-29",
        status="有效",
        article_text="保护劳动者合法权益。",
    )
    connector = LvyanLawTextConnector(tmp_path)
    sync = LegalSourceSyncService(LegalSourceService(session_factory), connector)

    first = await sync.sync(["中华人民共和国劳动法"])
    before_review = await DatabaseLegalKnowledgePort(session_factory).search(
        "劳动报酬",
        query_embedding=None,
        embedding_model=None,
    )

    assert first[0].outcome == "pending_review"
    assert before_review == []

    source_id = UUID(first[0].source_id or "")
    await sync.review(source_id, LegalSourceReviewStatus.approved)
    after_review = await DatabaseLegalKnowledgePort(session_factory).search(
        "劳动报酬",
        query_embedding=None,
        embedding_model=None,
    )
    second = await sync.sync(["中华人民共和国劳动法"])

    assert after_review[0].title == "中华人民共和国劳动法"
    assert second[0].outcome == "unchanged"
    assert second[0].source_id == first[0].source_id
