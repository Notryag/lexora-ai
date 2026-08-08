from __future__ import annotations

from uuid import UUID, uuid4

from lexora_ai.application.ports import CaseAnalysisGateway
from lexora_ai.domain import CaseAnalysisRequest, CaseAnalysisResult


class AnalyzeCaseService:
    def __init__(self, gateway: CaseAnalysisGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        request: CaseAnalysisRequest,
        *,
        analysis_id: UUID | None = None,
    ) -> CaseAnalysisResult:
        resolved_analysis_id = analysis_id or uuid4()
        generated = await self._gateway.analyze(
            request,
            analysis_id=resolved_analysis_id,
        )
        content = generated.content.strip()
        if not content:
            raise RuntimeError("analysis provider returned an empty response")
        return CaseAnalysisResult(
            analysis_id=resolved_analysis_id,
            case_title=request.case_title,
            analysis=content,
            material_count=len(request.materials),
            runtime_thread_id=generated.runtime_thread_id,
        )

