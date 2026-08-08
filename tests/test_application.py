from __future__ import annotations

from uuid import UUID

import pytest

from lexora_ai.application import (
    AnalyzeCaseService,
    GeneratedCaseAnalysis,
    GeneratedConversationTurn,
    LegalConversationService,
)
from lexora_ai.domain import CaseAnalysisRequest, CaseMaterial, ConversationTurnRequest


class FakeGateway:
    def __init__(self, content: str = "## 案情摘要\n已整理。") -> None:
        self.content = content
        self.received: CaseAnalysisRequest | None = None

    async def analyze(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID,
    ) -> GeneratedCaseAnalysis:
        self.received = request
        return GeneratedCaseAnalysis(content=self.content, runtime_thread_id=str(analysis_id))


class FakeConversationGateway:
    async def converse(
        self,
        request: ConversationTurnRequest,
        *,
        thread_id: UUID,
    ) -> GeneratedConversationTurn:
        return GeneratedConversationTurn(
            content=f"需要进一步确认：{request.message}",
            runtime_thread_id=str(thread_id),
        )


@pytest.mark.asyncio
async def test_service_returns_product_result() -> None:
    gateway = FakeGateway()
    service = AnalyzeCaseService(gateway)
    request = CaseAnalysisRequest(
        case_title="合同争议",
        materials=[CaseMaterial(title="合同", content="交付后付款。")],
    )

    result = await service.execute(request)

    assert result.case_title == "合同争议"
    assert result.material_count == 1
    assert result.analysis.startswith("## 案情摘要")
    assert result.runtime_thread_id == str(result.analysis_id)
    assert gateway.received is request


@pytest.mark.asyncio
async def test_service_rejects_empty_provider_response() -> None:
    service = AnalyzeCaseService(FakeGateway("  "))
    request = CaseAnalysisRequest(
        case_title="合同争议",
        materials=[CaseMaterial(title="合同", content="交付后付款。")],
    )

    with pytest.raises(RuntimeError, match="empty response"):
        await service.execute(request)


@pytest.mark.asyncio
async def test_conversation_service_creates_and_reuses_thread() -> None:
    service = LegalConversationService(FakeConversationGateway())
    first = await service.execute(ConversationTurnRequest(message="描述我的情况"))
    second = await service.execute(
        ConversationTurnRequest(thread_id=first.thread_id, message="补充一个事实")
    )

    assert first.thread_id == second.thread_id
    assert second.assistant_message.endswith("补充一个事实")
