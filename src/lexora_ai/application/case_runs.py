from __future__ import annotations

from uuid import UUID

from agent_platform.application import AgentRunService
from agent_platform.core import UserContext

from lexora_ai.application.errors import (
    ActiveCaseRunNotFoundError,
    CaseNotFoundError,
)
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import CaseRun, CaseRunStatus


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
