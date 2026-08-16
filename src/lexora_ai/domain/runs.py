from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


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


class CaseRunActivityType(StrEnum):
    model_started = "model_started"
    model_completed = "model_completed"
    model_failed = "model_failed"
    tool_started = "tool_started"
    tool_completed = "tool_completed"
    tool_failed = "tool_failed"
    task_started = "task_started"
    task_running = "task_running"
    task_completed = "task_completed"
    task_failed = "task_failed"
    task_timed_out = "task_timed_out"


class CaseRunActivity(BaseModel):
    seq: int = Field(ge=1)
    type: CaseRunActivityType
    event_type: str
    content: str | None = None
    call_id: str | None = None
    caller: str | None = None
    kind: str | None = None
    parent_call_id: str | None = None
    status: str | None = None
    tool_name: str | None = None
    subagent_type: str | None = None
    task_id: str | None = None


class CaseRunActivityHistory(BaseModel):
    run_id: UUID
    status: CaseRunStatus
    activities: list[CaseRunActivity] = Field(default_factory=list)
    completed_at: datetime | None = None
