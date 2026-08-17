from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agent_platform.core import (
    AgentRunEvent,
    AgentRunEventCategory,
    EventExtensionEnvelope,
    UserContext,
)
from pydantic import ValidationError

from lexora_ai.application.ports import RuntimeEventSink
from lexora_ai.db.session import SessionFactory
from lexora_ai.db.unit_of_work import LexoraUnitOfWork
from lexora_ai.domain import CaseRunActivity

logger = logging.getLogger(__name__)

_ACTIVITY_EXTENSION_KIND = "lexora.runtime.activity"


@dataclass(frozen=True, slots=True)
class ProjectedRunEvent:
    event_type: str
    category: AgentRunEventCategory
    content: str | None
    extension: EventExtensionEnvelope


def project_runtime_event(event: object) -> ProjectedRunEvent | None:
    """Convert a North event into a safe, product-neutral Lexora activity."""

    event_type = _text(getattr(event, "event_type", None))
    metadata = getattr(event, "metadata", {})
    if not isinstance(metadata, Mapping):
        metadata = {}
    raw_content = getattr(event, "content", {})
    event_content = raw_content if isinstance(raw_content, Mapping) else {}

    mapping: dict[str, tuple[AgentRunEventCategory, str | None]] = {
        "model.started": (AgentRunEventCategory.model, "正在分析"),
        "model.completed": (
            AgentRunEventCategory.model,
            "分析步骤已完成",
        ),
        "model.error": (AgentRunEventCategory.error, "分析过程发生错误"),
        "tool.started": (AgentRunEventCategory.tool, "正在调用工具"),
        "tool.completed": (
            AgentRunEventCategory.tool,
            "工具调用已完成",
        ),
        "tool.error": (AgentRunEventCategory.error, "工具调用失败"),
        "subagent.start": (
            AgentRunEventCategory.subagent,
            "正在执行子任务",
        ),
        "subagent.step": (
            AgentRunEventCategory.subagent,
            None,
        ),
        "subagent.end": (
            AgentRunEventCategory.subagent,
            _subagent_end_content(event_content.get("status")),
        ),
    }
    mapped = mapping.get(event_type)
    if mapped is None:
        return None
    category, content = mapped
    return ProjectedRunEvent(
        event_type=event_type,
        category=category,
        content=content,
        extension=EventExtensionEnvelope(
            kind=_ACTIVITY_EXTENSION_KIND,
            schema_version=1,
            payload=_safe_payload(event_type, metadata, event_content),
        ),
    )


def live_activity_payload(event: ProjectedRunEvent) -> dict[str, object]:
    return _activity_fields(
        event.event_type,
        content=event.content,
        payload=event.extension.payload,
    )


def persisted_run_activity(event: AgentRunEvent) -> CaseRunActivity | None:
    extension = event.extension
    if (
        extension is None
        or extension.kind != _ACTIVITY_EXTENSION_KIND
        or extension.schema_version != 1
    ):
        return None
    try:
        return CaseRunActivity.model_validate(
            {
                "seq": event.seq,
                **_activity_fields(
                    event.event_type,
                    content=_persisted_activity_content(
                        event.event_type,
                        extension.payload.get("status"),
                    ),
                    payload=extension.payload,
                ),
            }
        )
    except (KeyError, ValidationError):
        logger.warning(
            "Ignoring malformed persisted runtime activity",
            extra={"run_id": str(event.run_id), "event_type": event.event_type},
        )
        return None


class RunJournal:
    """Persist projected runtime activity without owning agent execution."""

    def __init__(
        self,
        session_factory: SessionFactory,
        context: UserContext,
        *,
        thread_id: UUID,
        run_id: UUID,
        on_event: RuntimeEventSink | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._thread_id = thread_id
        self._run_id = run_id
        self._on_event = on_event

    async def __call__(self, event: object) -> None:
        projected = project_runtime_event(event)
        if projected is None:
            return
        try:
            async with self._session_factory() as session:
                unit_of_work = LexoraUnitOfWork(session)
                if await unit_of_work.runs.get(self._context, self._run_id) is None:
                    return
                await unit_of_work.events.append(
                    self._context,
                    thread_id=self._thread_id,
                    run_id=self._run_id,
                    event_type=projected.event_type,
                    category=projected.category,
                    content=projected.content,
                    extension=projected.extension,
                )
                await unit_of_work.commit()
        except Exception:
            # Observability must not turn a successful model run into a failed run.
            logger.exception(
                "Lexora runtime event persistence failed",
                extra={"run_id": str(self._run_id), "event_type": projected.event_type},
            )
            return
        if self._on_event is not None:
            try:
                await self._on_event(projected)
            except Exception:
                logger.exception(
                    "Lexora runtime event publication failed",
                    extra={"run_id": str(self._run_id), "event_type": projected.event_type},
                )


def _safe_payload(
    event_type: str,
    metadata: Mapping[str, Any],
    content: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {
        "call_id",
        "call_index",
        "caller",
        "description",
        "display_name",
        "latency_ms",
        "parent_call_id",
        "tool_name",
        "task_id",
        "subagent_type",
        "message_index",
        "kind",
        "status",
        "truncated",
        "result_truncated",
        "error_type",
        "usage",
    }
    payload: dict[str, Any] = {"runtime_event": event_type}
    for key in allowed:
        value = metadata.get(key, content.get(key))
        if key == "usage":
            if isinstance(value, Mapping):
                safe_usage = {
                    usage_key: usage_value
                    for usage_key in (
                        "input_tokens",
                        "output_tokens",
                        "total_tokens",
                        "cached_input_tokens",
                    )
                    if isinstance((usage_value := value.get(usage_key)), int)
                    and not isinstance(usage_value, bool)
                    and usage_value >= 0
                }
                if safe_usage:
                    payload[key] = safe_usage
            continue
        if key == "description" and isinstance(value, str):
            value = " ".join(value.split())[:120]
        if isinstance(value, (str, int, float, bool)):
            payload[key] = value
    if event_type == "tool.started" and "description" not in payload:
        description = _tool_activity_description(
            _text(metadata.get("tool_name")),
            _text(content.get("query")),
        )
        if description is not None:
            payload["description"] = description
    return payload


def _tool_activity_description(tool_name: str | None, query: str | None) -> str | None:
    if not query:
        return None
    label = {
        "search_case_materials": "案件材料",
        "search_legal_authorities": "法规依据",
        "search_guiding_cases": "相关案例",
    }.get(tool_name)
    if label is None:
        return None
    preview = " ".join(query.split())[:80]
    return f"检索“{preview}”相关的{label}"


def _activity_fields(
    event_type: str,
    *,
    content: str | None,
    payload: Mapping[str, Any],
) -> dict[str, object]:
    status = payload.get("status")
    live_type = {
        "model.started": "model_started",
        "model.completed": "model_completed",
        "model.error": "model_failed",
        "tool.started": "tool_started",
        "tool.completed": "tool_completed",
        "tool.error": "tool_failed",
        "subagent.start": "task_started",
        "subagent.step": "task_running",
        "subagent.end": (
            "task_completed"
            if status == "completed"
            else "task_timed_out"
            if status == "timed_out"
            else "task_failed"
        ),
    }[event_type]
    return {
        **payload,
        "type": live_type,
        "event_type": event_type,
        "content": content,
    }


def _subagent_end_content(status: object) -> str:
    return {
        "completed": "子任务已完成",
        "failed": "子任务执行失败",
        "timed_out": "子任务执行超时",
    }.get(status, "子任务已结束")


def _persisted_activity_content(event_type: str, status: object) -> str | None:
    if event_type == "subagent.end":
        return _subagent_end_content(status)
    return {
        "model.started": "正在分析",
        "model.completed": "分析步骤已完成",
        "model.error": "分析过程发生错误",
        "tool.started": "正在调用工具",
        "tool.completed": "工具调用已完成",
        "tool.error": "工具调用失败",
        "subagent.start": "正在执行子任务",
        "subagent.step": None,
    }[event_type]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
