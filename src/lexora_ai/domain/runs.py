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
    model_name: str | None = None
    error: str | None = None
    message_count: int = 0
    first_human_message: str | None = None
    last_ai_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
