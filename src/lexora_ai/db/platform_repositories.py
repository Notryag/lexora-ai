from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from agent_platform.core import (
    AgentRun,
    AgentRunEvent,
    AgentRunEventCategory,
    AgentRunStatus,
    ConversationMessage,
    ConversationRole,
    ConversationState,
    ConversationThread,
    ConversationThreadStatus,
    EventExtensionEnvelope,
    IdempotencyClaim,
    IdempotencyRecord,
    PendingInteraction,
    PresentationEnvelope,
    UserContext,
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lexora_ai.db.models import (
    AgentRunEventRow,
    AgentRunRow,
    ConversationMessageRow,
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


def message_from_row(row: ConversationMessageRow) -> ConversationMessage:
    presentation = PresentationEnvelope.model_validate(row.presentation) if row.presentation else None
    return ConversationMessage(
        id=row.id,
        thread_id=row.thread_id,
        run_id=row.run_id,
        role=ConversationRole(row.role),
        content=row.content,
        presentation=presentation,
        created_at=row.created_at,
    )


def run_from_row(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        id=row.id,
        user_id=row.owner_id,
        thread_id=row.thread_id,
        status=AgentRunStatus(row.status),
        input_message=row.input_message,
        result_message=row.result_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def event_from_row(row: AgentRunEventRow) -> AgentRunEvent:
    extension = EventExtensionEnvelope.model_validate(row.extension) if row.extension else None
    return AgentRunEvent(
        id=row.id,
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
            row = ConversationThreadRow(
                owner_id=context.user_id,
                case_id=case_id,
                is_primary=False,
                title=title,
                status=ConversationThreadStatus.active.value,
            )
            self.session.add(row)
            await self.session.flush()
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


class ConversationMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append_once(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        run_id: UUID,
        role: ConversationRole,
        content: str,
        presentation: PresentationEnvelope | None = None,
    ) -> ConversationMessage:
        existing = await self.session.scalar(
            select(ConversationMessageRow).where(
                ConversationMessageRow.owner_id == context.user_id,
                ConversationMessageRow.run_id == run_id,
                ConversationMessageRow.role == role.value,
            )
        )
        if existing is not None:
            return message_from_row(existing)
        row = ConversationMessageRow(
            owner_id=context.user_id,
            thread_id=thread_id,
            run_id=run_id,
            role=role.value,
            content=content,
            presentation=presentation.model_dump(mode="json") if presentation else None,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return message_from_row(row)

    async def upsert_assistant(
        self,
        context: UserContext,
        *,
        thread_id: UUID,
        run_id: UUID,
        content: str,
        presentation: PresentationEnvelope | None,
    ) -> ConversationMessage:
        row = await self.session.scalar(
            select(ConversationMessageRow).where(
                ConversationMessageRow.owner_id == context.user_id,
                ConversationMessageRow.run_id == run_id,
                ConversationMessageRow.role == ConversationRole.assistant.value,
            )
        )
        if row is None:
            return await self.append_once(
                context,
                thread_id=thread_id,
                run_id=run_id,
                role=ConversationRole.assistant,
                content=content,
                presentation=presentation,
            )
        row.content = content
        row.presentation = presentation.model_dump(mode="json") if presentation else None
        await self.session.flush()
        await self.session.refresh(row)
        return message_from_row(row)

    async def get_assistant_for_run(
        self,
        context: UserContext,
        run_id: UUID,
    ) -> ConversationMessage | None:
        row = await self.session.scalar(
            select(ConversationMessageRow).where(
                ConversationMessageRow.owner_id == context.user_id,
                ConversationMessageRow.run_id == run_id,
                ConversationMessageRow.role == ConversationRole.assistant.value,
            )
        )
        return message_from_row(row) if row else None

    async def list_for_thread(
        self,
        context: UserContext,
        thread_id: UUID,
    ) -> list[ConversationMessage]:
        rows = await self.session.scalars(
            select(ConversationMessageRow)
            .where(
                ConversationMessageRow.owner_id == context.user_id,
                ConversationMessageRow.thread_id == thread_id,
            )
            .order_by(ConversationMessageRow.created_at.asc(), ConversationMessageRow.id.asc())
        )
        return [message_from_row(row) for row in rows]

    async def list_page_for_thread(
        self,
        context: UserContext,
        thread_id: UUID,
        *,
        before: UUID | None,
        limit: int,
    ) -> tuple[list[ConversationMessage], UUID | None]:
        messages = await self.list_for_thread(context, thread_id)
        if before is not None:
            cursor = next((index for index, item in enumerate(messages) if item.id == before), None)
            if cursor is None:
                raise LookupError("Conversation message cursor not found")
            messages = messages[:cursor]
        page = messages[-limit:]
        return page, page[0].id if len(messages) > len(page) else None


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        context: UserContext,
        *,
        input_message: str,
        thread_id: UUID | None,
        status: AgentRunStatus,
        run_id: UUID | None,
    ) -> AgentRun:
        if thread_id is None:
            raise ValueError("thread_id is required for Lexora runs")
        row = AgentRunRow(
            id=run_id or uuid4(),
            owner_id=context.user_id,
            thread_id=thread_id,
            status=status.value,
            input_message=input_message,
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
        result_message: str | None = None,
    ) -> AgentRun | None:
        row = await self.session.scalar(
            update(AgentRunRow)
            .where(
                AgentRunRow.id == run_id,
                AgentRunRow.owner_id == context.user_id,
                AgentRunRow.status.in_([item.value for item in from_statuses]),
            )
            .values(status=status.value, result_message=result_message, updated_at=func.now())
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
        run_id: UUID,
        event_type: str,
        category: AgentRunEventCategory,
        content: str | None = None,
        extension: EventExtensionEnvelope | None = None,
    ) -> AgentRunEvent:
        run = await self.session.scalar(
            select(AgentRunRow)
            .where(AgentRunRow.id == run_id, AgentRunRow.owner_id == context.user_id)
            .with_for_update()
        )
        if run is None:
            raise LookupError("Agent run not found")
        next_seq = (
            await self.session.scalar(
                select(func.coalesce(func.max(AgentRunEventRow.seq), 0)).where(
                    AgentRunEventRow.run_id == run_id
                )
            )
        ) + 1
        row = AgentRunEventRow(
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
