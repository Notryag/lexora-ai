from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from agent_platform.core import (
    AgentRun,
    AgentRunEvent,
    AgentRunEventCategory,
    AgentRunStatus,
    ConversationRole,
    ConversationState,
    ConversationThread,
    ConversationThreadStatus,
    EventExtensionEnvelope,
    IdempotencyClaim,
    IdempotencyRecord,
    PendingInteraction,
    UserContext,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lexora_ai.db.models import (
    AgentRunEventRow,
    AgentRunRow,
    ConversationStateRow,
    ConversationThreadRow,
    IdempotencyRow,
)


def thread_from_row(row: ConversationThreadRow) -> ConversationThread:
    return ConversationThread(
        id=row.id,
        user_id=row.owner_id,
        is_primary=row.is_primary,
        title=row.title,
        status=ConversationThreadStatus(row.status),
        summary=row.summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def run_from_row(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        id=row.id,
        user_id=row.owner_id,
        thread_id=row.thread_id,
        status=AgentRunStatus(row.status),
        model_name=row.model_name,
        error=row.error,
        message_count=row.message_count,
        first_human_message=row.first_human_message,
        last_ai_message=row.last_ai_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def event_from_row(row: AgentRunEventRow) -> AgentRunEvent:
    extension = EventExtensionEnvelope.model_validate(row.extension) if row.extension else None
    return AgentRunEvent(
        id=row.id,
        thread_id=row.thread_id,
        run_id=row.run_id,
        seq=row.seq,
        event_type=row.event_type,
        category=AgentRunEventCategory(row.category),
        content=row.content,
        extension=extension,
        created_at=row.created_at,
    )


def idempotency_from_row(row: IdempotencyRow) -> IdempotencyRecord:
    return IdempotencyRecord(
        id=row.id,
        user_id=row.owner_id,
        key=row.key,
        request_hash=row.request_hash,
        run_id=row.run_id,
        created_at=row.created_at,
    )


class ConversationThreadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        context: UserContext,
        *,
        thread_id: UUID | None = None,
        title: str | None = None,
    ) -> ConversationThread:
        row = ConversationThreadRow(
            id=thread_id or uuid4(),
            owner_id=context.user_id,
            case_id=None,
            is_primary=False,
            title=title,
            status=ConversationThreadStatus.active.value,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return thread_from_row(row)

    async def get_or_create_for_case(
        self,
        context: UserContext,
        *,
        case_id: UUID,
        title: str,
    ) -> ConversationThread:
        row = await self.session.scalar(
            select(ConversationThreadRow).where(
                ConversationThreadRow.owner_id == context.user_id,
                ConversationThreadRow.case_id == case_id,
            )
        )
        if row is None:
            try:
                async with self.session.begin_nested():
                    row = ConversationThreadRow(
                        owner_id=context.user_id,
                        case_id=case_id,
                        is_primary=False,
                        title=title,
                        status=ConversationThreadStatus.active.value,
                    )
                    self.session.add(row)
                    await self.session.flush()
            except IntegrityError:
                row = await self.session.scalar(
                    select(ConversationThreadRow).where(
                        ConversationThreadRow.owner_id == context.user_id,
                        ConversationThreadRow.case_id == case_id,
                    )
                )
                if row is None:
                    raise
            await self.session.refresh(row)
        return thread_from_row(row)

    async def get(self, context: UserContext, thread_id: UUID) -> ConversationThread | None:
        row = await self.session.scalar(
            select(ConversationThreadRow).where(
                ConversationThreadRow.id == thread_id,
                ConversationThreadRow.owner_id == context.user_id,
            )
        )
        return thread_from_row(row) if row else None

    async def get_for_case(
        self,
        context: UserContext,
        case_id: UUID,
    ) -> ConversationThread | None:
        row = await self.session.scalar(
            select(ConversationThreadRow).where(
                ConversationThreadRow.owner_id == context.user_id,
                ConversationThreadRow.case_id == case_id,
            )
        )
        return thread_from_row(row) if row else None

    async def get_or_create_primary(self, context: UserContext) -> ConversationThread:
        row = await self.session.scalar(
            select(ConversationThreadRow).where(
                ConversationThreadRow.owner_id == context.user_id,
                ConversationThreadRow.is_primary.is_(True),
            )
        )
        if row is not None:
            return thread_from_row(row)
        thread = await self.create(context)
        await self.session.execute(
            update(ConversationThreadRow)
            .where(ConversationThreadRow.id == thread.id)
            .values(is_primary=True)
        )
        row = await self.session.get(ConversationThreadRow, thread.id)
        return thread_from_row(row)

    async def update_summary(
        self,
        context: UserContext,
        thread_id: UUID,
        summary: str,
    ) -> ConversationThread | None:
        row = await self.session.scalar(
            update(ConversationThreadRow)
            .where(
                ConversationThreadRow.id == thread_id,
                ConversationThreadRow.owner_id == context.user_id,
            )
            .values(summary=summary, updated_at=func.now())
            .returning(ConversationThreadRow)
        )
        return thread_from_row(row) if row else None

    async def get_runtime_checkpoint(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> tuple[str, str] | None:
        row = (
            await self.session.execute(
                select(
                    ConversationThreadRow.runtime_checkpoint_ns,
                    ConversationThreadRow.runtime_checkpoint_id,
                ).where(
                    ConversationThreadRow.id == thread_id,
                    ConversationThreadRow.owner_id == context.user_id,
                )
            )
        ).one_or_none()
        if row is None or row.runtime_checkpoint_id is None:
            return None
        if row.runtime_checkpoint_ns is None:
            raise RuntimeError("Persisted checkpoint ID has no namespace")
        return row.runtime_checkpoint_ns, row.runtime_checkpoint_id

    async def get_runtime_checkpoint_id(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> str | None:
        checkpoint = await self.get_runtime_checkpoint(context, thread_id)
        return checkpoint[1] if checkpoint is not None else None

    async def update_runtime_checkpoint(
        self,
        context: UserContext,
        thread_id: UUID,
        *,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> bool:
        result = await self.session.execute(
            update(ConversationThreadRow)
            .where(
                ConversationThreadRow.id == thread_id,
                ConversationThreadRow.owner_id == context.user_id,
            )
            .values(
                runtime_checkpoint_ns=checkpoint_ns,
                runtime_checkpoint_id=checkpoint_id,
                updated_at=func.now(),
            )
        )
        return result.rowcount == 1


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        status: AgentRunStatus,
        run_id: UUID | None,
        model_name: str | None = None,
        first_human_message: str | None = None,
    ) -> AgentRun:
        row = AgentRunRow(
            id=run_id or uuid4(),
            owner_id=context.user_id,
            thread_id=thread_id,
            status=status.value,
            model_name=model_name,
            message_count=1 if first_human_message else 0,
            first_human_message=first_human_message,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return run_from_row(row)

    async def transition_status(
        self,
        context: UserContext,
        run_id: UUID,
        *,
        from_statuses: set[AgentRunStatus],
        status: AgentRunStatus,
        error: str | None = None,
        message_count: int | None = None,
        first_human_message: str | None = None,
        last_ai_message: str | None = None,
    ) -> AgentRun | None:
        values: dict[str, Any] = {"status": status.value, "updated_at": func.now()}
        if error is not None:
            values["error"] = error
        if message_count is not None:
            values["message_count"] = message_count
        if first_human_message is not None:
            values["first_human_message"] = first_human_message
        if last_ai_message is not None:
            values["last_ai_message"] = last_ai_message
        now = datetime.now(UTC)
        if status == AgentRunStatus.running:
            values["started_at"] = now
        elif status in {
            AgentRunStatus.completed,
            AgentRunStatus.needs_clarification,
            AgentRunStatus.failed,
            AgentRunStatus.cancelled,
        }:
            values["completed_at"] = now
        row = await self.session.scalar(
            update(AgentRunRow)
            .where(
                AgentRunRow.id == run_id,
                AgentRunRow.owner_id == context.user_id,
                AgentRunRow.status.in_([item.value for item in from_statuses]),
            )
            .values(**values)
            .returning(AgentRunRow)
        )
        return run_from_row(row) if row else None

    async def get(self, context: UserContext, run_id: UUID) -> AgentRun | None:
        row = await self.session.scalar(
            select(AgentRunRow).where(
                AgentRunRow.id == run_id,
                AgentRunRow.owner_id == context.user_id,
            )
        )
        return run_from_row(row) if row else None

    async def get_for_update(self, context: UserContext, run_id: UUID) -> AgentRun | None:
        row = await self.session.scalar(
            select(AgentRunRow)
            .where(AgentRunRow.id == run_id, AgentRunRow.owner_id == context.user_id)
            .with_for_update()
        )
        return run_from_row(row) if row else None

    async def get_for_worker(self, run_id: UUID) -> AgentRun | None:
        row = await self.session.get(AgentRunRow, run_id)
        return run_from_row(row) if row else None

    async def get_active_for_thread(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> AgentRun | None:
        row = await self.session.scalar(
            select(AgentRunRow).where(
                AgentRunRow.owner_id == context.user_id,
                AgentRunRow.thread_id == thread_id,
                AgentRunRow.status.in_([AgentRunStatus.queued.value, AgentRunStatus.running.value]),
            )
        )
        return run_from_row(row) if row else None

    async def get_latest_for_thread(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> AgentRun | None:
        row = await self.session.scalar(
            select(AgentRunRow)
            .where(
                AgentRunRow.owner_id == context.user_id,
                AgentRunRow.thread_id == thread_id,
            )
            .order_by(AgentRunRow.updated_at.desc(), AgentRunRow.created_at.desc())
            .limit(1)
        )
        return run_from_row(row) if row else None

    async def list_stale_running(self, *, updated_before: datetime) -> list[AgentRun]:
        rows = await self.session.scalars(
            select(AgentRunRow).where(
                AgentRunRow.status == AgentRunStatus.running.value,
                AgentRunRow.updated_at < updated_before,
            )
        )
        return [run_from_row(row) for row in rows]

    async def list_stale_queued(self, *, created_before: datetime) -> list[AgentRun]:
        rows = await self.session.scalars(
            select(AgentRunRow).where(
                AgentRunRow.status == AgentRunStatus.queued.value,
                AgentRunRow.created_at < created_before,
            )
        )
        return [run_from_row(row) for row in rows]


class AgentRunEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        run_id: UUID,
        event_type: str,
        category: AgentRunEventCategory,
        content: str | None = None,
        extension: EventExtensionEnvelope | None = None,
    ) -> AgentRunEvent:
        locked_thread = await self.session.scalar(
            select(ConversationThreadRow.id)
            .where(
                ConversationThreadRow.id == thread_id,
                ConversationThreadRow.owner_id == context.user_id,
            )
            .with_for_update()
        )
        if locked_thread is None:
            raise LookupError("Conversation thread not found")
        run = await self.session.scalar(
            select(AgentRunRow.id).where(
                AgentRunRow.id == run_id,
                AgentRunRow.owner_id == context.user_id,
                AgentRunRow.thread_id == thread_id,
            )
        )
        if run is None:
            raise LookupError("Agent run not found for thread")
        next_seq = (
            await self.session.scalar(
                select(func.coalesce(func.max(AgentRunEventRow.seq), 0)).where(
                    AgentRunEventRow.thread_id == thread_id
                )
            )
        ) + 1
        row = AgentRunEventRow(
            owner_id=context.user_id,
            thread_id=thread_id,
            run_id=run_id,
            seq=next_seq,
            event_type=event_type,
            category=category.value,
            content=content,
            extension=extension.model_dump(mode="json") if extension else None,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return event_from_row(row)

    async def append_message_once(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        run_id: UUID,
        role: ConversationRole,
        content: str,
        extension: EventExtensionEnvelope | None = None,
    ) -> AgentRunEvent:
        event_type = _message_event_type(role)
        existing = await self._get_event_row(context, run_id, event_type)
        if existing is not None:
            if role == ConversationRole.assistant:
                if content:
                    existing.content = content
                if extension is not None:
                    existing.extension = extension.model_dump(mode="json")
                await self.session.flush()
                await self.session.refresh(existing)
            return event_from_row(existing)
        return await self.append(
            context,
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category=AgentRunEventCategory.message,
            content=content,
            extension=extension,
        )

    async def append_execution_input_once(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        run_id: UUID,
        content: str,
    ) -> AgentRunEvent:
        existing = await self._get_event_row(context, run_id, "agent.input")
        if existing is not None:
            return event_from_row(existing)
        return await self.append(
            context,
            thread_id=thread_id,
            run_id=run_id,
            event_type="agent.input",
            category=AgentRunEventCategory.model,
            content=content,
        )

    async def list_for_run(
        self,
        context: UserContext,
        run_id: UUID,
        *,
        after_seq: int = 0,
    ) -> list[AgentRunEvent]:
        run = await self.session.scalar(
            select(AgentRunRow.id).where(
                AgentRunRow.id == run_id,
                AgentRunRow.owner_id == context.user_id,
            )
        )
        if run is None:
            return []
        rows = await self.session.scalars(
            select(AgentRunEventRow)
            .where(AgentRunEventRow.run_id == run_id, AgentRunEventRow.seq > after_seq)
            .order_by(AgentRunEventRow.seq.asc())
        )
        return [event_from_row(row) for row in rows]

    async def get_message_for_run(
        self,
        context: UserContext,
        run_id: UUID,
        role: ConversationRole,
    ) -> AgentRunEvent | None:
        row = await self._get_event_row(context, run_id, _message_event_type(role))
        return event_from_row(row) if row else None

    async def get_execution_input_for_run(
        self,
        context: UserContext,
        run_id: UUID,
    ) -> AgentRunEvent | None:
        row = await self._get_event_row(context, run_id, "agent.input")
        return event_from_row(row) if row else None

    async def list_messages_for_thread(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> list[AgentRunEvent]:
        rows = await self.session.scalars(
            select(AgentRunEventRow)
            .where(
                AgentRunEventRow.owner_id == context.user_id,
                AgentRunEventRow.thread_id == thread_id,
                AgentRunEventRow.category == AgentRunEventCategory.message.value,
            )
            .order_by(AgentRunEventRow.seq.asc())
        )
        return [event_from_row(row) for row in rows]

    async def list_message_page_for_thread(
        self,
        context: UserContext,
        thread_id: UUID,
        *,
        before: UUID | None,
        limit: int,
    ) -> tuple[list[AgentRunEvent], UUID | None]:
        statement = select(AgentRunEventRow).where(
            AgentRunEventRow.owner_id == context.user_id,
            AgentRunEventRow.thread_id == thread_id,
            AgentRunEventRow.category == AgentRunEventCategory.message.value,
        )
        if before is not None:
            cursor = await self.session.scalar(
                select(AgentRunEventRow).where(
                    AgentRunEventRow.id == before,
                    AgentRunEventRow.owner_id == context.user_id,
                    AgentRunEventRow.thread_id == thread_id,
                    AgentRunEventRow.category == AgentRunEventCategory.message.value,
                )
            )
            if cursor is None:
                raise LookupError("Conversation message cursor not found")
            statement = statement.where(AgentRunEventRow.seq < cursor.seq)
        rows = list(
            await self.session.scalars(
                statement.order_by(AgentRunEventRow.seq.desc()).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        page.reverse()
        return [event_from_row(row) for row in page], page[0].id if has_more else None

    async def _get_event_row(
        self,
        context: UserContext,
        run_id: UUID,
        event_type: str,
    ) -> AgentRunEventRow | None:
        return await self.session.scalar(
            select(AgentRunEventRow).where(
                AgentRunEventRow.owner_id == context.user_id,
                AgentRunEventRow.run_id == run_id,
                AgentRunEventRow.event_type == event_type,
            )
        )


def _message_event_type(role: ConversationRole) -> str:
    return {
        ConversationRole.user: "message.human",
        ConversationRole.assistant: "message.ai",
    }[role]


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, context: UserContext, *, key: str) -> IdempotencyRecord | None:
        row = await self.session.scalar(
            select(IdempotencyRow).where(
                IdempotencyRow.owner_id == context.user_id,
                IdempotencyRow.key == key,
            )
        )
        return idempotency_from_row(row) if row else None

    async def claim(
        self,
        context: UserContext,
        *,
        key: str,
        request_hash: str,
        run_id: UUID,
    ) -> IdempotencyClaim:
        existing = await self.get(context, key=key)
        if existing is not None:
            return IdempotencyClaim(record=existing, created=False)
        row = IdempotencyRow(
            owner_id=context.user_id,
            key=key,
            request_hash=request_hash,
            run_id=run_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return IdempotencyClaim(record=idempotency_from_row(row), created=True)

    async def delete_created_before(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            delete(IdempotencyRow).where(IdempotencyRow.created_at < cutoff)
        )
        return int(result.rowcount or 0)


class ConversationStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _from_row(row: ConversationStateRow) -> ConversationState:
        interaction = PendingInteraction.model_validate(row.interaction) if row.interaction else None
        return ConversationState(
            thread_id=row.thread_id,
            interaction=interaction,
            version=row.version,
            expires_at=row.expires_at,
            updated_at=row.updated_at,
        )

    async def get(self, context: UserContext, thread_id: UUID) -> ConversationState | None:
        row = await self.session.scalar(
            select(ConversationStateRow).where(
                ConversationStateRow.thread_id == thread_id,
                ConversationStateRow.owner_id == context.user_id,
            )
        )
        return self._from_row(row) if row else None

    async def set_interaction(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        interaction: PendingInteraction,
        expires_at: datetime,
    ) -> ConversationState:
        row = await self.session.get(ConversationStateRow, thread_id)
        if row is None:
            row = ConversationStateRow(
                thread_id=thread_id,
                owner_id=context.user_id,
                interaction=interaction.model_dump(mode="json"),
                expires_at=expires_at,
            )
            self.session.add(row)
        else:
            row.interaction = interaction.model_dump(mode="json")
            row.expires_at = expires_at
            row.version += 1
        await self.session.flush()
        await self.session.refresh(row)
        return self._from_row(row)

    async def consume_interaction(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        expected_version: int,
        consumed_at: datetime,
    ) -> ConversationState | None:
        row = await self.session.scalar(
            update(ConversationStateRow)
            .where(
                ConversationStateRow.thread_id == thread_id,
                ConversationStateRow.owner_id == context.user_id,
                ConversationStateRow.version == expected_version,
                ConversationStateRow.interaction.is_not(None),
                ConversationStateRow.expires_at > consumed_at,
            )
            .values(
                interaction=None,
                expires_at=None,
                version=ConversationStateRow.version + 1,
                updated_at=func.now(),
            )
            .returning(ConversationStateRow)
        )
        return self._from_row(row) if row else None

    async def clear_interaction(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> ConversationState | None:
        row = await self.session.scalar(
            update(ConversationStateRow)
            .where(
                ConversationStateRow.thread_id == thread_id,
                ConversationStateRow.owner_id == context.user_id,
            )
            .values(
                interaction=None,
                expires_at=None,
                version=ConversationStateRow.version + 1,
                updated_at=func.now(),
            )
            .returning(ConversationStateRow)
        )
        return self._from_row(row) if row else None
