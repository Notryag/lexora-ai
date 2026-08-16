from __future__ import annotations

from uuid import UUID

from agent_platform.application import AgentRunService
from agent_platform.core import UserContext

from lexora_ai.application.errors import (
    ActiveCaseRunNotFoundError,
    CaseNotFoundError,
)
from lexora_ai.application.run_journal import persisted_run_activity
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import CaseRun, CaseRunActivityHistory, CaseRunStatus

_ACTIVITY_HISTORY_LIMIT = 256


def _run_status(run, *, status: CaseRunStatus | None = None) -> CaseRun:
    return CaseRun(
        run_id=run.id,
        status=status or CaseRunStatus(run.status.value),
        model_name=run.model_name,
        error=run.error,
        message_count=run.message_count,
        first_human_message=run.first_human_message,
        last_ai_message=run.last_ai_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


class CaseRunService:
    def __init__(self, session_factory: SessionFactory, context: UserContext) -> None:
        self._session_factory = session_factory
        self._context = context

    async def get_latest(self, case_id: UUID) -> CaseRun | None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if await unit_of_work.cases.get(self._context, case_id) is None:
                raise CaseNotFoundError("Case not found")
            thread = await unit_of_work.threads.get_for_case(self._context, case_id)
            if thread is None:
                return None
            run = await unit_of_work.runs.get_latest_for_thread(self._context, thread.id)
            return _run_status(run) if run else None

    async def get_for_case(self, case_id: UUID, run_id: UUID) -> CaseRun | None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if await unit_of_work.cases.get(self._context, case_id) is None:
                raise CaseNotFoundError("Case not found")
            thread = await unit_of_work.threads.get_for_case(self._context, case_id)
            if thread is None:
                return None
            run = await unit_of_work.runs.get(self._context, run_id)
            if run is None or run.thread_id != thread.id:
                return None
            return _run_status(run)

    async def get_latest_activity_history(
        self,
        case_id: UUID,
    ) -> CaseRunActivityHistory | None:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if await unit_of_work.cases.get(self._context, case_id) is None:
                raise CaseNotFoundError("Case not found")
            thread = await unit_of_work.threads.get_for_case(self._context, case_id)
            if thread is None:
                return None
            run = await unit_of_work.runs.get_latest_for_thread(self._context, thread.id)
            if run is None:
                return None
            events = await unit_of_work.events.list_for_run(
                self._context,
                run.id,
                limit=_ACTIVITY_HISTORY_LIMIT,
            )
            return CaseRunActivityHistory(
                run_id=run.id,
                status=CaseRunStatus(run.status.value),
                activities=[
                    activity
                    for event in events
                    if (activity := persisted_run_activity(event)) is not None
                ],
                completed_at=run.completed_at,
            )

    async def cancel_active(self, case_id: UUID) -> CaseRun:
        async with self._session_factory() as session:
            unit_of_work = LexoraUnitOfWork(session)
            if await unit_of_work.cases.get(self._context, case_id) is None:
                raise CaseNotFoundError("Case not found")
            thread = await unit_of_work.threads.get_for_case(self._context, case_id)
            if thread is None:
                raise ActiveCaseRunNotFoundError("This case has no active analysis")
            run = await unit_of_work.runs.get_active_for_thread(self._context, thread.id)
            if run is None:
                raise ActiveCaseRunNotFoundError("This case has no active analysis")
            if not await AgentRunService(unit_of_work).mark_cancelled(
                self._context,
                run,
                event_content="analysis cancelled by user",
            ):
                raise ActiveCaseRunNotFoundError("This analysis is no longer active")
            await unit_of_work.commit()
            return _run_status(run, status=CaseRunStatus.cancelled)
