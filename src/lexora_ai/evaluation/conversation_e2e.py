from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, model_validator

from lexora_ai.domain import (
    CaseConversationMessage,
    CaseConversationTurnResult,
    CaseRun,
    LegalCase,
)

DEFAULT_SCENARIOS_PATH = (
    Path(__file__).resolve().parents[3] / "evaluation/conversation_e2e.json"
)
EVALUATION_CASE_PREFIX = "[conversation-eval:"


class TurnExpectation(BaseModel):
    required_term_groups: list[list[str]] = Field(default_factory=list)
    required_key_fact_groups: list[list[str]] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    min_legal_citations: int = Field(default=0, ge=0)
    max_legal_citations: int | None = Field(default=None, ge=0)
    min_case_law_citations: int = Field(default=0, ge=0)
    max_case_law_citations: int | None = Field(default=None, ge=0)
    max_answer_chars: int | None = Field(default=None, ge=1)
    max_questions: int | None = Field(default=None, ge=0)
    min_delta_events: int = Field(default=1, ge=1)
    require_profile_update: bool = False
    forbidden_factor_states: list[FactorStatePattern] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ranges(self) -> TurnExpectation:
        if (
            self.max_legal_citations is not None
            and self.max_legal_citations < self.min_legal_citations
        ):
            raise ValueError("max_legal_citations must be at least min_legal_citations")
        if (
            self.max_case_law_citations is not None
            and self.max_case_law_citations < self.min_case_law_citations
        ):
            raise ValueError("max_case_law_citations must be at least min_case_law_citations")
        if any(
            not group or any(not term.strip() for term in group)
            for groups in (self.required_term_groups, self.required_key_fact_groups)
            for group in groups
        ):
            raise ValueError("required term groups cannot be empty")
        return self


class FactorStatePattern(BaseModel):
    key_or_label_terms: list[str] = Field(min_length=1)
    state: str = Field(min_length=1)


class ConversationEvaluationTurn(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    expect: TurnExpectation = Field(default_factory=TurnExpectation)
    review: list[str] = Field(default_factory=list)


class ConversationEvaluationScenario(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=120)
    turns: list[ConversationEvaluationTurn] = Field(min_length=1, max_length=4)


class ConversationEvaluationSuite(BaseModel):
    version: int = Field(ge=1)
    scenarios: list[ConversationEvaluationScenario] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> ConversationEvaluationSuite:
        ids = [scenario.id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario ids must be unique")
        return self


class ConversationEvaluationError(RuntimeError):
    pass


class ConversationEvaluationInfrastructureError(ConversationEvaluationError):
    pass


class StreamObservation(BaseModel):
    result: CaseConversationTurnResult
    streamed_text: str
    delta_events: int
    first_token_seconds: float | None
    total_seconds: float


def load_suite(path: Path = DEFAULT_SCENARIOS_PATH) -> ConversationEvaluationSuite:
    return ConversationEvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


def select_scenarios(
    suite: ConversationEvaluationSuite,
    scenario_ids: Sequence[str],
    *,
    max_scenarios: int,
) -> list[ConversationEvaluationScenario]:
    if max_scenarios < 1 or max_scenarios > 20:
        raise ValueError("max_scenarios must be between 1 and 20")
    by_id = {scenario.id: scenario for scenario in suite.scenarios}
    requested = list(dict.fromkeys(scenario_ids))
    unknown = [scenario_id for scenario_id in requested if scenario_id not in by_id]
    if unknown:
        raise ValueError(f"unknown scenarios: {', '.join(unknown)}")
    selected = [by_id[scenario_id] for scenario_id in requested] if requested else suite.scenarios
    if len(selected) > max_scenarios:
        raise ValueError(
            f"selected {len(selected)} scenarios but max_scenarios is {max_scenarios}"
        )
    return selected


def build_plan(
    scenarios: Sequence[ConversationEvaluationScenario],
    *,
    base_url: str,
) -> dict[str, object]:
    return {
        "mode": "dry-run",
        "base_url": base_url.rstrip("/"),
        "scenario_count": len(scenarios),
        "agent_turn_limit": sum(len(scenario.turns) for scenario in scenarios),
        "internal_model_calls": None,
        "token_usage": None,
        "cost_note": (
            "No request was sent. Internal Agent model-call and token usage are not exposed "
            "by the current runtime contract; --execute bounds scenarios and user turns only."
        ),
        "scenarios": [
            {
                "id": scenario.id,
                "title": scenario.title,
                "turns": len(scenario.turns),
                "review": [item for turn in scenario.turns for item in turn.review],
            }
            for scenario in scenarios
        ],
    }


async def execute_suite(
    scenarios: Sequence[ConversationEvaluationScenario],
    *,
    base_url: str,
    timeout_seconds: float = 180.0,
    keep_cases: bool = False,
    client: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    owned_client = client is None
    resolved_client = client or httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=httpx.Timeout(timeout_seconds),
    )
    evaluation_id = uuid4().hex[:12]
    started_at = datetime.now(UTC)
    scenario_reports: list[dict[str, object]] = []
    try:
        await _require_healthy(resolved_client)
        for scenario in scenarios:
            scenario_reports.append(
                await _execute_scenario(
                    resolved_client,
                    scenario,
                    evaluation_id=evaluation_id,
                    keep_case=keep_cases,
                    clock=clock,
                )
            )
    finally:
        if owned_client:
            await resolved_client.aclose()
    failures = [
        failure
        for scenario_report in scenario_reports
        for failure in scenario_report.get("failures", [])
    ]
    infrastructure_failures = [
        failure
        for scenario_report in scenario_reports
        for failure in scenario_report.get("infrastructure_failures", [])
    ]
    completed_at = datetime.now(UTC)
    return {
        "mode": "execute",
        "evaluation_id": evaluation_id,
        "base_url": base_url.rstrip("/"),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "passed": not failures and not infrastructure_failures,
        "quality_passed": None if infrastructure_failures else not failures,
        "scenario_count": len(scenario_reports),
        "agent_turns": sum(
            len(scenario_report.get("turns", [])) for scenario_report in scenario_reports
        ),
        "agent_runs": sum(
            int(scenario_report.get("run_count", 0)) for scenario_report in scenario_reports
        ),
        "internal_model_calls": None,
        "token_usage": None,
        "observability_note": (
            "Agent-internal model calls and token usage are unavailable in the current public "
            "Run/event contract. The report does not estimate them."
        ),
        "failures": failures,
        "infrastructure_failures": infrastructure_failures,
        "scenarios": scenario_reports,
    }


async def _execute_scenario(
    client: httpx.AsyncClient,
    scenario: ConversationEvaluationScenario,
    *,
    evaluation_id: str,
    keep_case: bool,
    clock: Callable[[], float],
) -> dict[str, object]:
    case: LegalCase | None = None
    turn_reports: list[dict[str, object]] = []
    failures: list[str] = []
    report: dict[str, object] = {
        "id": scenario.id,
        "title": scenario.title,
        "case_id": None,
        "passed": False,
        "message_count": 0,
        "run_count": 0,
        "turns": turn_reports,
        "failures": failures,
        "infrastructure_failures": [],
        "cleanup": "kept" if keep_case else "not-created",
    }
    try:
        response = await client.post(
            "/api/v1/cases",
            json={
                "title": f"{EVALUATION_CASE_PREFIX}{evaluation_id}] {scenario.title}",
                "background": "自动化核心对话验收创建；结束后按案件 ID 清理。",
            },
        )
        _raise_for_status(response, "create evaluation case")
        case = LegalCase.model_validate(response.json())
        for turn_index, turn in enumerate(scenario.turns, start=1):
            observation = await _stream_turn(
                client,
                case.id,
                turn.message,
                clock=clock,
            )
            turn_failures = _evaluate_turn(observation, turn.expect)
            turn_reports.append(
                {
                    "turn": turn_index,
                    "message": turn.message,
                    "answer": observation.result.assistant_message,
                    "follow_up_questions": _extract_questions(
                        observation.result.assistant_message
                    ),
                    "legal_citations": [
                        citation.model_dump(mode="json")
                        for citation in observation.result.legal_citations
                    ],
                    "case_law_citations": [
                        citation.model_dump(mode="json")
                        for citation in observation.result.case_law_citations
                    ],
                    "case_profile": observation.result.case_profile.model_dump(mode="json"),
                    "profile_updated": observation.result.profile_updated,
                    "run_id": str(observation.result.run_id),
                    "stream": {
                        "delta_events": observation.delta_events,
                        "streamed_chars": len(observation.streamed_text),
                        "first_token_seconds": observation.first_token_seconds,
                        "total_seconds": observation.total_seconds,
                    },
                    "automated_failures": turn_failures,
                    "manual_review": turn.review,
                }
            )
            failures.extend(
                f"{scenario.id}/turn-{turn_index}: {failure}"
                for failure in turn_failures
            )
        persistence = await _evaluate_persistence(client, case.id, turn_reports)
        failures.extend(f"{scenario.id}: {failure}" for failure in persistence["failures"])
        report = {
            "id": scenario.id,
            "title": scenario.title,
            "case_id": str(case.id),
            "passed": not failures,
            "message_count": persistence["message_count"],
            "run_count": persistence["run_count"],
            "latest_run": persistence["latest_run"],
            "turns": turn_reports,
            "failures": failures,
            "cleanup": "kept" if keep_case else "pending",
        }
    except ConversationEvaluationInfrastructureError as exc:
        infrastructure_failure = f"{scenario.id}: infrastructure error: {exc}"
        report = {
            "id": scenario.id,
            "title": scenario.title,
            "case_id": str(case.id) if case else None,
            "passed": False,
            "message_count": 0,
            "run_count": len(turn_reports),
            "turns": turn_reports,
            "failures": failures,
            "infrastructure_failures": [infrastructure_failure],
            "cleanup": "kept" if keep_case else "pending",
        }
    except Exception as exc:
        failure = f"{scenario.id}: execution error: {type(exc).__name__}: {exc}"
        failures.append(failure)
        report = {
            "id": scenario.id,
            "title": scenario.title,
            "case_id": str(case.id) if case else None,
            "passed": False,
            "message_count": 0,
            "run_count": len(turn_reports),
            "turns": turn_reports,
            "failures": failures,
            "infrastructure_failures": [],
            "cleanup": "kept" if keep_case else "pending",
        }
    finally:
        if case is not None and not keep_case:
            try:
                response = await client.delete(f"/api/v1/cases/{case.id}")
                if response.status_code == 204:
                    report["cleanup"] = "deleted"
                else:
                    cleanup_failure = (
                        f"{scenario.id}: cleanup returned HTTP {response.status_code}"
                    )
                    failures.append(cleanup_failure)
                    report["cleanup"] = "failed"
            except Exception as exc:
                cleanup_failure = (
                    f"{scenario.id}: cleanup error: {type(exc).__name__}: {exc}"
                )
                failures.append(cleanup_failure)
                report["cleanup"] = "failed"
        report["passed"] = not failures and not report.get("infrastructure_failures", [])
        report["failures"] = failures
    return report


async def _stream_turn(
    client: httpx.AsyncClient,
    case_id: object,
    message: str,
    *,
    clock: Callable[[], float],
) -> StreamObservation:
    started = clock()
    first_delta_at: float | None = None
    deltas: list[str] = []
    result: CaseConversationTurnResult | None = None
    async with client.stream(
        "POST",
        f"/api/v1/cases/{case_id}/messages/stream",
        json={"message": message},
        headers={"Accept": "application/x-ndjson"},
    ) as response:
        if response.status_code >= 400:
            body = (await response.aread()).decode(errors="replace")
            raise ConversationEvaluationError(
                f"stream request returned HTTP {response.status_code}: {body[:500]}"
            )
        content_type = response.headers.get("content-type", "")
        if "application/x-ndjson" not in content_type:
            raise ConversationEvaluationError(
                f"stream response has unexpected content type: {content_type or 'missing'}"
            )
        async for line in response.aiter_lines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConversationEvaluationError("stream returned invalid NDJSON") from exc
            event_type = event.get("type")
            if event_type == "delta":
                delta = event.get("delta")
                if not isinstance(delta, str) or not delta:
                    raise ConversationEvaluationError("stream returned an empty delta")
                if first_delta_at is None:
                    first_delta_at = clock()
                deltas.append(delta)
            elif event_type == "complete":
                if result is not None:
                    raise ConversationEvaluationError("stream returned multiple complete events")
                result = CaseConversationTurnResult.model_validate(event.get("result"))
            elif event_type == "error":
                message = str(event.get("message") or "stream failed")
                if event.get("code") == "provider_unavailable":
                    raise ConversationEvaluationInfrastructureError(message)
                raise ConversationEvaluationError(message)
            else:
                raise ConversationEvaluationError(f"stream returned unknown event type: {event_type}")
    completed = clock()
    if result is None:
        raise ConversationEvaluationError("stream ended without a complete event")
    return StreamObservation(
        result=result,
        streamed_text="".join(deltas),
        delta_events=len(deltas),
        first_token_seconds=(
            round(first_delta_at - started, 4) if first_delta_at is not None else None
        ),
        total_seconds=round(completed - started, 4),
    )


def _evaluate_turn(
    observation: StreamObservation,
    expectation: TurnExpectation,
) -> list[str]:
    answer = observation.result.assistant_message
    failures: list[str] = []
    if observation.streamed_text != answer:
        failures.append("streamed text does not equal the persisted final answer")
    if observation.delta_events < expectation.min_delta_events:
        failures.append(
            f"expected at least {expectation.min_delta_events} delta events, "
            f"got {observation.delta_events}"
        )
    if expectation.require_profile_update and not observation.result.profile_updated:
        failures.append("expected case profile update")
    for terms in expectation.required_term_groups:
        if not any(term.casefold() in answer.casefold() for term in terms):
            failures.append(f"answer is missing one of required terms: {terms}")
    key_facts = "\n".join(observation.result.case_profile.key_facts).casefold()
    for terms in expectation.required_key_fact_groups:
        if not any(term.casefold() in key_facts for term in terms):
            failures.append(f"case profile key facts are missing one of required terms: {terms}")
    for term in expectation.forbidden_terms:
        if term.casefold() in answer.casefold():
            failures.append(f"answer contains forbidden repeated or irrelevant prompt: {term}")
    if expectation.max_answer_chars is not None and len(answer) > expectation.max_answer_chars:
        failures.append(
            f"answer has {len(answer)} chars; maximum is {expectation.max_answer_chars}"
        )
    question_count = len(_extract_questions(answer))
    if expectation.max_questions is not None and question_count > expectation.max_questions:
        failures.append(
            f"answer has {question_count} follow-up questions; maximum is "
            f"{expectation.max_questions}"
        )
    legal_count = len(observation.result.legal_citations)
    case_law_count = len(observation.result.case_law_citations)
    _check_count(
        failures,
        label="legal citations",
        actual=legal_count,
        minimum=expectation.min_legal_citations,
        maximum=expectation.max_legal_citations,
    )
    _check_count(
        failures,
        label="case-law citations",
        actual=case_law_count,
        minimum=expectation.min_case_law_citations,
        maximum=expectation.max_case_law_citations,
    )
    for pattern in expectation.forbidden_factor_states:
        for factor in observation.result.case_profile.factor_profile.factors:
            searchable = f"{factor.key} {factor.label}".casefold()
            if factor.state.value == pattern.state and any(
                term.casefold() in searchable for term in pattern.key_or_label_terms
            ):
                failures.append(
                    f"case profile contains forbidden factor state: {factor.key}="
                    f"{factor.state.value}"
                )
    return failures


async def _evaluate_persistence(
    client: httpx.AsyncClient,
    case_id: object,
    turn_reports: Sequence[dict[str, object]],
) -> dict[str, object]:
    messages_response = await client.get(f"/api/v1/cases/{case_id}/messages")
    _raise_for_status(messages_response, "list persisted messages")
    messages = [
        CaseConversationMessage.model_validate(item) for item in messages_response.json()
    ]
    run_response = await client.get(f"/api/v1/cases/{case_id}/run")
    _raise_for_status(run_response, "get latest run")
    latest_run = CaseRun.model_validate(run_response.json())
    failures: list[str] = []
    expected_message_count = len(turn_reports) * 2
    if len(messages) != expected_message_count:
        failures.append(
            f"expected {expected_message_count} persisted messages, got {len(messages)}"
        )
    expected_roles = [role for _ in turn_reports for role in ("user", "assistant")]
    actual_roles = [message.role for message in messages]
    if actual_roles != expected_roles:
        failures.append(f"persisted message roles are not alternating: {actual_roles}")
    expected_run_ids = [str(turn["run_id"]) for turn in turn_reports]
    persisted_run_ids = {str(message.run_id) for message in messages}
    if persisted_run_ids != set(expected_run_ids):
        failures.append("persisted messages do not map one-to-one to observed Runs")
    for run_id in expected_run_ids:
        if sum(str(message.run_id) == run_id for message in messages) != 2:
            failures.append(f"Run {run_id} does not have exactly one human and one AI message")
    if latest_run.status.value != "completed":
        failures.append(f"latest Run status is {latest_run.status.value}, expected completed")
    if expected_run_ids and str(latest_run.run_id) != expected_run_ids[-1]:
        failures.append("latest Run ID does not match the final streamed turn")
    if latest_run.message_count != 2:
        failures.append(
            f"latest Run message_count is {latest_run.message_count}, expected 2"
        )
    return {
        "message_count": len(messages),
        "run_count": len(persisted_run_ids),
        "latest_run": latest_run.model_dump(mode="json"),
        "failures": failures,
    }


async def _require_healthy(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    _raise_for_status(response, "health check")
    payload = response.json()
    if payload.get("status") != "ok":
        raise ConversationEvaluationError("Lexora API health status is not ok")


def _raise_for_status(response: httpx.Response, action: str) -> None:
    if response.status_code < 400:
        return
    try:
        detail: Any = response.json()
    except json.JSONDecodeError:
        detail = response.text[:500]
    raise ConversationEvaluationError(
        f"{action} returned HTTP {response.status_code}: {detail}"
    )


def _extract_questions(answer: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.findall(r"[^\n。！？?!]*[？?]", answer)
        if segment.strip()
    ]


def _check_count(
    failures: list[str],
    *,
    label: str,
    actual: int,
    minimum: int,
    maximum: int | None,
) -> None:
    if actual < minimum:
        failures.append(f"expected at least {minimum} {label}, got {actual}")
    if maximum is not None and actual > maximum:
        failures.append(f"expected at most {maximum} {label}, got {actual}")
