from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from north.runtime import MemoryStreamBridge

from lexora_ai.api.app import create_app
from lexora_ai.api.dependencies import (
    get_analyze_case_service,
    get_case_run_service,
    get_legal_conversation_service,
    get_persistent_conversation_service,
    get_stream_bridge,
)
from lexora_ai.application import (
    AnalyzeCaseService,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
    LegalConversationService,
)
from lexora_ai.domain import (
    CaseAnalysisRequest,
    CaseConversationTurnResult,
    CaseRunActivity,
    CaseRunActivityHistory,
    CaseRunActivityType,
    CaseRunStatus,
    ConversationTurnRequest,
)
from lexora_ai.infrastructure import (
    ModelNotConfiguredError,
    ModelTemporarilyUnavailableError,
)


class FakeGateway:
    async def analyze(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID,
    ) -> GeneratedCaseAnalysis:
        return GeneratedCaseAnalysis(
            content="## 案情摘要\n合同约定交付后付款。[M1]",
            runtime_thread_id=str(analysis_id),
        )

    async def converse(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
    ) -> GeneratedConversationTurn:
        return GeneratedConversationTurn(
            content=f"请补充说明：{request.message}",
            runtime_thread_id=str(thread_id),
        )


class UnconfiguredGateway:
    async def analyze(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID,
    ) -> GeneratedCaseAnalysis:
        del request, analysis_id
        raise ModelNotConfiguredError("OPENAI_API_KEY is not configured")


class FakePersistentConversationService:
    def __init__(self, bridge: MemoryStreamBridge) -> None:
        self.bridge = bridge

    async def execute(self, case_id, request, *, on_text_delta=None, on_run_started=None):
        del on_text_delta
        result = CaseConversationTurnResult(
            case_id=case_id,
            thread_id=UUID("018f6f7c-3500-7c4a-83e7-64dd8aa83293"),
            run_id=UUID("018f6f7c-3500-7c4a-83e7-64dd8aa83294"),
            assistant_message=f"你好，已收到：{request.message}",
            material_count=0,
        )
        if on_run_started is not None:
            await on_run_started(result.run_id)
        run_id = str(result.run_id)
        await self.bridge.publish(
            run_id,
            "metadata",
            {"run_id": run_id, "thread_id": str(result.thread_id)},
        )
        await self.bridge.publish(run_id, "messages", {"delta": "你"})
        await self.bridge.publish(run_id, "messages", {"delta": "好"})
        await self.bridge.publish(
            run_id,
            "complete",
            {"result": result.model_dump(mode="json")},
        )
        await self.bridge.publish_end(run_id)
        return result


class UnavailablePersistentConversationService:
    async def execute(
        self,
        case_id,
        request,
        *,
        on_text_delta=None,
        on_run_started=None,
    ):
        del case_id, request, on_text_delta, on_run_started
        raise ModelTemporarilyUnavailableError("模型服务暂时不可用，请稍后重试。")


class FakeCaseRunService:
    async def get_latest_activity_history(self, case_id):
        return CaseRunActivityHistory(
            run_id=UUID("018f6f7c-3500-7c4a-83e7-64dd8aa83294"),
            status=CaseRunStatus.completed,
            activities=[
                CaseRunActivity(
                    seq=3,
                    type=CaseRunActivityType.tool_completed,
                    event_type="tool.completed",
                    content="工具调用已完成",
                    call_id="search-1",
                    caller="subagent:legal_researcher",
                    tool_name="search_legal_authorities",
                )
            ],
            completed_at=datetime(2026, 8, 16, tzinfo=UTC),
        )


def parse_sse(text: str) -> list[dict[str, object]]:
    events = []
    for frame in text.strip().split("\n\n"):
        event: dict[str, object] = {}
        for line in frame.splitlines():
            if line.startswith("id: "):
                event["id"] = line[4:]
            elif line.startswith("event: "):
                event["event"] = line[7:]
            elif line.startswith("data: "):
                event["data"] = json.loads(line[6:])
        if event:
            events.append(event)
    return events


def build_client() -> TestClient:
    app = create_app()
    gateway = FakeGateway()
    app.dependency_overrides[get_analyze_case_service] = lambda: AnalyzeCaseService(gateway)
    app.dependency_overrides[get_legal_conversation_service] = lambda: LegalConversationService(
        gateway
    )
    return TestClient(app)


def test_health() -> None:
    response = build_client().get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "lexora-ai", "version": "0.1.0"}


def test_case_conversation_stream_returns_deltas_and_completion() -> None:
    app = create_app()
    bridge = MemoryStreamBridge()
    app.dependency_overrides[get_stream_bridge] = lambda: bridge
    app.dependency_overrides[get_persistent_conversation_service] = lambda: (
        FakePersistentConversationService(bridge)
    )
    case_id = "018f6f7c-3500-7c4a-83e7-64dd8aa83291"

    response = TestClient(app).post(
        f"/api/v1/cases/{case_id}/messages/stream",
        json={"message": "hi"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [event["event"] for event in events] == [
        "metadata",
        "messages",
        "messages",
        "complete",
        "end",
    ]
    assert events[1]["data"] == {"delta": "你"}
    assert events[2]["data"] == {"delta": "好"}
    result = events[3]["data"]["result"]
    assert result["assistant_message"] == "你好，已收到：hi"
    assert result["profile_updated"] is False
    assert result["case_profile"]["key_facts"] == []


def test_case_conversation_stream_classifies_provider_unavailability() -> None:
    app = create_app()
    bridge = MemoryStreamBridge()
    app.dependency_overrides[get_stream_bridge] = lambda: bridge
    app.dependency_overrides[get_persistent_conversation_service] = (
        UnavailablePersistentConversationService
    )
    case_id = "018f6f7c-3500-7c4a-83e7-64dd8aa83291"

    response = TestClient(app).post(
        f"/api/v1/cases/{case_id}/messages/stream",
        json={"message": "hi"},
    )

    assert response.status_code == 200
    assert parse_sse(response.text) == [
        {
            "event": "error",
            "data": {
                "code": "provider_unavailable",
                "message": "模型服务暂时不可用，请稍后重试。",
            },
        }
    ]


def test_case_run_activities_returns_persisted_safe_projection() -> None:
    app = create_app()
    app.dependency_overrides[get_case_run_service] = FakeCaseRunService
    case_id = "018f6f7c-3500-7c4a-83e7-64dd8aa83291"

    response = TestClient(app).get(f"/api/v1/cases/{case_id}/run/activities")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "018f6f7c-3500-7c4a-83e7-64dd8aa83294",
        "status": "completed",
        "activities": [
            {
                "seq": 3,
                "type": "tool_completed",
                "event_type": "tool.completed",
                "content": "工具调用已完成",
                "call_id": "search-1",
                "caller": "subagent:legal_researcher",
                "kind": None,
                "parent_call_id": None,
                "status": None,
                "tool_name": "search_legal_authorities",
                "subagent_type": None,
                "task_id": None,
            }
        ],
        "completed_at": "2026-08-16T00:00:00Z",
    }


def test_create_analysis() -> None:
    response = build_client().post(
        "/api/v1/analyses",
        json={
            "case_title": "买卖合同争议",
            "questions": ["是否完成交付？"],
            "materials": [
                {
                    "title": "合同",
                    "kind": "contract",
                    "content": "合同约定交付后支付尾款。",
                }
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["case_title"] == "买卖合同争议"
    assert payload["material_count"] == 1
    assert payload["runtime_thread_id"] == payload["analysis_id"]
    assert payload["analysis"].endswith("[M1]")
    assert "不构成法律意见" in payload["disclaimer"]


def test_create_analysis_rejects_missing_materials() -> None:
    response = build_client().post(
        "/api/v1/analyses",
        json={"case_title": "缺少材料", "materials": []},
    )

    assert response.status_code == 422


def test_create_analysis_reports_missing_model_configuration() -> None:
    app = create_app()
    app.dependency_overrides[get_analyze_case_service] = lambda: AnalyzeCaseService(
        UnconfiguredGateway()
    )
    client = TestClient(app)

    response = client.post(
        "/api/v1/analyses",
        json={
            "case_title": "合同争议",
            "materials": [{"title": "合同", "content": "交付后付款。"}],
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "OPENAI_API_KEY is not configured"}


def test_create_and_continue_legal_conversation() -> None:
    client = build_client()
    first = client.post(
        "/api/v1/conversations/messages",
        json={"message": "公司突然通知我不用上班了。"},
    )

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["assistant_message"].startswith("请补充说明")

    second = client.post(
        "/api/v1/conversations/messages",
        json={
            "thread_id": first_payload["thread_id"],
            "message": "我已经工作三年。",
        },
    )

    assert second.status_code == 200
    assert second.json()["thread_id"] == first_payload["thread_id"]
