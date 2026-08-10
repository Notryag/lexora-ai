from __future__ import annotations

import json
from uuid import UUID

from fastapi.testclient import TestClient

from lexora_ai.api.app import create_app
from lexora_ai.api.dependencies import (
    get_analyze_case_service,
    get_legal_conversation_service,
    get_persistent_conversation_service,
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
    ConversationTurnRequest,
)
from lexora_ai.infrastructure import ModelNotConfiguredError


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
    async def execute(self, case_id, request, *, on_text_delta=None):
        if on_text_delta is not None:
            on_text_delta("你")
            on_text_delta("好")
        return CaseConversationTurnResult(
            case_id=case_id,
            thread_id=UUID("018f6f7c-3500-7c4a-83e7-64dd8aa83293"),
            run_id=UUID("018f6f7c-3500-7c4a-83e7-64dd8aa83294"),
            assistant_message=f"你好，已收到：{request.message}",
            material_count=0,
        )


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
    app.dependency_overrides[get_persistent_conversation_service] = (
        FakePersistentConversationService
    )
    case_id = "018f6f7c-3500-7c4a-83e7-64dd8aa83291"

    response = TestClient(app).post(
        f"/api/v1/cases/{case_id}/messages/stream",
        json={"message": "hi"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0] == {"type": "delta", "delta": "你"}
    assert events[1] == {"type": "delta", "delta": "好"}
    assert events[2]["type"] == "complete"
    assert events[2]["result"]["assistant_message"] == "你好，已收到：hi"
    assert events[2]["result"]["profile_updated"] is False
    assert events[2]["result"]["case_profile"]["key_facts"] == []


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
