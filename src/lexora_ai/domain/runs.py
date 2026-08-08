from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class CaseRunStatus(StrEnum):
    queued = "queued"
    running = "running"
    needs_clarification = "needs_clarification"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class CaseRun(BaseModel):
    run_id: UUID
    status: CaseRunStatus
    input_message: str
    result_message: str | None
    created_at: datetime
    updated_at: datetime
