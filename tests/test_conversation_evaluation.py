from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from lexora_ai.domain import CaseConversationTurnResult
from lexora_ai.evaluation.conversation_e2e import (
    ConversationEvaluationScenario,
    ConversationEvaluationTurn,
    FactorStatePattern,
    StreamObservation,
    TurnExpectation,
    _evaluate_turn,
    build_plan,
    execute_suite,
    load_suite,
    select_scenarios,
)

CASE_ID = UUID("00000000-0000-0000-0000-000000000101")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000102")
RUN_ID = UUID("00000000-0000-0000-0000-000000000103")
HUMAN_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000104")
AI_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000105")
NOW = datetime(2026, 8, 15, tzinfo=UTC).isoformat()


def test_default_suite_has_a_bounded_dry_run_plan() -> None:
    suite = load_suite()
    scenarios = select_scenarios(suite, [], max_scenarios=5)

    plan = build_plan(scenarios, base_url="http://127.0.0.1:8011/")

    assert plan["mode"] == "dry-run"
    assert plan["scenario_count"] == 5
    assert plan["agent_turn_limit"] == 6
    assert plan["internal_model_calls"] is None
    assert plan["token_usage"] is None


def test_select_scenarios_rejects_unknown_or_excessive_live_scope() -> None:
    suite = load_suite()

    with pytest.raises(ValueError, match="unknown scenarios"):
        select_scenarios(suite, ["missing"], max_scenarios=5)
    with pytest.raises(ValueError, match="selected 5 scenarios"):
        select_scenarios(suite, [], max_scenarios=4)


def test_turn_evaluation_rejects_an_overbroad_persisted_factor() -> None:
    payload = _turn_result_payload("不等于自动离婚，也不能直接认定为重婚。")
    payload["case_profile"]["factor_profile"]["factors"] = [  # type: ignore[index]
        {
            "key": "cohabitation.present",
            "label": "是否共同生活",
            "type": "boolean",
            "state": "denied",
            "value": False,
            "materiality": "high",
            "question": None,
            "source_turns": [],
            "source_material_refs": [],
        }
    ]
    result = CaseConversationTurnResult.model_validate(payload)
    observation = StreamObservation(
        result=result,
        streamed_text=result.assistant_message,
        delta_events=2,
        first_token_seconds=0.1,
        total_seconds=0.2,
    )

    failures = _evaluate_turn(
        observation,
        TurnExpectation(
            forbidden_factor_states=[
                FactorStatePattern(
                    key_or_label_terms=["cohabitation.present", "是否共同生活"],
                    state="denied",
                )
            ]
        ),
    )

    assert failures == [
        "case profile contains forbidden factor state: cohabitation.present=denied"
    ]


def test_turn_evaluation_requires_user_facts_in_case_profile() -> None:
    payload = _turn_result_payload("盗窃案件需要结合金额判断。")
    payload["case_profile"]["key_facts"] = ["盗窃财物价值约5万元"]  # type: ignore[index]
    result = CaseConversationTurnResult.model_validate(payload)
    observation = StreamObservation(
        result=result,
        streamed_text=result.assistant_message,
        delta_events=1,
        first_token_seconds=0.1,
        total_seconds=0.2,
    )

    failures = _evaluate_turn(
        observation,
        TurnExpectation(
            required_key_fact_groups=[
                ["约5万元", "约五万元"],
                ["未退赃"],
            ]
        ),
    )

    assert failures == [
        "case profile key facts are missing one of required terms: ['未退赃']"
    ]


def test_turn_evaluation_can_require_a_profile_update() -> None:
    result = CaseConversationTurnResult.model_validate(_turn_result_payload("已完成分析。"))
    observation = StreamObservation(
        result=result,
        streamed_text=result.assistant_message,
        delta_events=1,
        first_token_seconds=0.1,
        total_seconds=0.2,
    )

    failures = _evaluate_turn(
        observation,
        TurnExpectation(require_profile_update=True),
    )

    assert failures == ["expected case profile update"]


@pytest.mark.asyncio
async def test_execute_suite_checks_stream_persistence_and_exact_cleanup() -> None:
    requests: list[tuple[str, str]] = []
    scenario = ConversationEvaluationScenario(
        id="fixture",
        title="测试场景",
        turns=[
            ConversationEvaluationTurn(
                message="hi",
                expect=TurnExpectation(
                    required_term_groups=[["你好"]],
                    max_questions=0,
                    min_delta_events=2,
                ),
            )
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v1/cases" and request.method == "POST":
            return httpx.Response(201, json=_case_payload())
        if request.url.path.endswith("/messages/stream"):
            result = _turn_result_payload("你好，请描述你的法律问题。")
            events = [
                ("metadata", {"run_id": str(RUN_ID)}),
                ("messages", {"delta": "你好，"}),
                ("custom", {"type": "agent.started", "content": "正在分析"}),
                ("messages", {"delta": "请描述你的法律问题。"}),
                ("complete", {"result": result}),
                ("end", {}),
            ]
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content="".join(
                    f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    for event, data in events
                ).encode(),
            )
        if request.url.path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json=_message_payloads())
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json=_run_payload())
        if request.url.path == f"/api/v1/cases/{CASE_ID}" and request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="http://lexora.test",
        transport=transport,
    ) as client:
        report = await execute_suite(
            [scenario],
            base_url="http://lexora.test",
            client=client,
        )

    assert report["passed"] is True
    assert report["agent_turns"] == 1
    assert report["agent_runs"] == 1
    scenario_report = report["scenarios"][0]
    assert scenario_report["message_count"] == 2
    assert scenario_report["cleanup"] == "deleted"
    assert scenario_report["turns"][0]["stream"]["delta_events"] == 2
    assert requests[-1] == ("DELETE", f"/api/v1/cases/{CASE_ID}")
    assert requests.count(("DELETE", f"/api/v1/cases/{CASE_ID}")) == 1


@pytest.mark.asyncio
async def test_execute_suite_reports_stream_mismatch_and_still_cleans_up() -> None:
    scenario = ConversationEvaluationScenario(
        id="fixture",
        title="测试场景",
        turns=[ConversationEvaluationTurn(message="hi")],
    )
    deleted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v1/cases" and request.method == "POST":
            return httpx.Response(201, json=_case_payload())
        if request.url.path.endswith("/messages/stream"):
            events = [
                {"type": "delta", "delta": "未过滤的回答"},
                {"type": "complete", "result": _turn_result_payload("最终回答")},
            ]
            return httpx.Response(
                200,
                headers={"Content-Type": "application/x-ndjson"},
                content="".join(
                    f"{json.dumps(event, ensure_ascii=False)}\n" for event in events
                ).encode(),
            )
        if request.url.path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json=_message_payloads(answer="最终回答"))
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json=_run_payload(answer="最终回答"))
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return httpx.Response(204)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://lexora.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        report = await execute_suite(
            [scenario],
            base_url="http://lexora.test",
            client=client,
        )

    assert report["passed"] is False
    assert "streamed text does not equal" in report["failures"][0]
    assert deleted == [f"/api/v1/cases/{CASE_ID}"]
    assert report["scenarios"][0]["cleanup"] == "deleted"


@pytest.mark.asyncio
async def test_execute_suite_separates_provider_failure_from_answer_quality() -> None:
    scenario = ConversationEvaluationScenario(
        id="fixture",
        title="测试场景",
        turns=[ConversationEvaluationTurn(message="hi")],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/v1/cases" and request.method == "POST":
            return httpx.Response(201, json=_case_payload())
        if request.url.path.endswith("/messages/stream"):
            event = {
                "type": "error",
                "code": "provider_unavailable",
                "message": "模型服务暂时不可用，请稍后重试。",
            }
            return httpx.Response(
                200,
                headers={"Content-Type": "application/x-ndjson"},
                content=f"{json.dumps(event, ensure_ascii=False)}\n".encode(),
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        base_url="http://lexora.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        report = await execute_suite(
            [scenario],
            base_url="http://lexora.test",
            client=client,
        )

    assert report["passed"] is False
    assert report["quality_passed"] is None
    assert report["failures"] == []
    assert "模型服务暂时不可用" in report["infrastructure_failures"][0]
    assert report["scenarios"][0]["cleanup"] == "deleted"


def _case_payload() -> dict[str, object]:
    return {
        "id": str(CASE_ID),
        "title": "测试场景",
        "background": None,
        "profile": _profile_payload(),
        "material_count": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _turn_result_payload(answer: str) -> dict[str, object]:
    return {
        "case_id": str(CASE_ID),
        "thread_id": str(THREAD_ID),
        "run_id": str(RUN_ID),
        "assistant_message": answer,
        "material_count": 0,
        "legal_citations": [],
        "case_law_citations": [],
        "profile_updated": False,
        "case_profile": _profile_payload(),
    }


def _message_payloads(answer: str = "你好，请描述你的法律问题。") -> list[dict[str, object]]:
    return [
        {
            "id": str(HUMAN_MESSAGE_ID),
            "thread_id": str(THREAD_ID),
            "run_id": str(RUN_ID),
            "role": "user",
            "content": "hi",
            "legal_citations": [],
            "case_law_citations": [],
            "created_at": NOW,
        },
        {
            "id": str(AI_MESSAGE_ID),
            "thread_id": str(THREAD_ID),
            "run_id": str(RUN_ID),
            "role": "assistant",
            "content": answer,
            "legal_citations": [],
            "case_law_citations": [],
            "created_at": NOW,
        },
    ]


def _run_payload(answer: str = "你好，请描述你的法律问题。") -> dict[str, object]:
    return {
        "run_id": str(RUN_ID),
        "status": "completed",
        "model_name": None,
        "error": None,
        "message_count": 2,
        "first_human_message": "hi",
        "last_ai_message": answer,
        "started_at": NOW,
        "completed_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _profile_payload() -> dict[str, object]:
    return {
        "case_type": None,
        "parties": [],
        "claims": [],
        "key_facts": [],
        "disputed_issues": [],
        "evidence_notes": [],
        "missing_information": [],
        "factor_profile": {"active_domains": [], "factors": []},
    }
