from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from agent_platform.core import AgentRunEventCategory, AgentRunStatus, UserContext
from north import RuntimeEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from lexora_ai.application import RunJournal, project_runtime_event
from lexora_ai.db.models import Base
from lexora_ai.db.unit_of_work import LexoraUnitOfWork


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


def test_runtime_projection_drops_raw_model_and_subagent_content() -> None:
    projected = project_runtime_event(
        RuntimeEvent(
            event_type="subagent.step",
            category="subagent",
            content={"text": "private intermediate analysis"},
            metadata={
                "task_id": "task-1",
                "message_index": 0,
                "kind": "ai",
                "secret": "must-not-persist",
            },
        )
    )

    assert projected is not None
    assert projected.category == AgentRunEventCategory.subagent
    assert projected.content is None
    assert projected.extension.payload == {
        "runtime_event": "subagent.step",
        "task_id": "task-1",
        "message_index": 0,
        "kind": "ai",
    }
    assert "private intermediate analysis" not in str(projected)
    assert "must-not-persist" not in str(projected)


def test_runtime_projection_keeps_bounded_subagent_activity_description() -> None:
    projected = project_runtime_event(
        RuntimeEvent(
            event_type="subagent.start",
            category="subagent",
            content={
                "description": "  梳理婚姻关系事实\n和回答目标  ",
                "task_id": "task-1",
            },
            metadata={"task_id": "task-1", "subagent_type": "case_analyst"},
        )
    )

    assert projected is not None
    assert projected.extension.payload["description"] == "梳理婚姻关系事实 和回答目标"


def test_runtime_projection_keeps_bounded_legal_search_description() -> None:
    projected = project_runtime_event(
        RuntimeEvent(
            event_type="tool.started",
            category="tool",
            content={"query": "  分居多年\n是否自动离婚  "},
            metadata={
                "call_id": "tool-1",
                "task_id": "research-task",
                "tool_name": "search_legal_authorities",
                "caller": "subagent:legal_researcher",
            },
        )
    )

    assert projected is not None
    assert projected.extension.payload["task_id"] == "research-task"
    assert projected.extension.payload["description"] == (
        "检索“分居多年 是否自动离婚”相关的法规依据"
    )
    assert "query" not in projected.extension.payload


@pytest.mark.asyncio
async def test_run_journal_persists_activity_in_existing_run_events_table(
    session_factory,
) -> None:
    context = UserContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        timezone="Asia/Shanghai",
        locale="zh-CN",
    )
    run_id = uuid4()
    async with session_factory() as session:
        unit_of_work = LexoraUnitOfWork(session)
        thread = await unit_of_work.threads.create(context, title="测试案件")
        await unit_of_work.runs.create(
            context,
            thread_id=thread.id,
            status=AgentRunStatus.running,
            run_id=run_id,
        )
        await unit_of_work.commit()

    journal = RunJournal(
        session_factory,
        context,
        thread_id=thread.id,
        run_id=run_id,
    )
    await journal(
        RuntimeEvent(
            event_type="tool.started",
            category="tool",
            content={"query": "sensitive case facts"},
            metadata={
                "call_id": "tool-1",
                "tool_name": "search_case_law",
                "caller": "subagent:legal_researcher",
            },
        )
    )

    async with session_factory() as session:
        unit_of_work = LexoraUnitOfWork(session)
        events = await unit_of_work.events.list_for_run(context, run_id)

    assert len(events) == 1
    assert events[0].event_type == "tool.started"
    assert events[0].category == AgentRunEventCategory.tool
    assert events[0].content == "正在调用工具"
    assert events[0].extension is not None
    assert events[0].extension.payload["call_id"] == "tool-1"
    assert "sensitive case facts" not in str(events[0])
