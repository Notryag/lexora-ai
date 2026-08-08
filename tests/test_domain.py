from __future__ import annotations

import pytest
from pydantic import ValidationError

from lexora_ai.domain import CaseAnalysisRequest, CaseMaterial
from lexora_ai.domain.cases import MAX_TOTAL_MATERIAL_CHARS


def test_request_normalizes_and_deduplicates_questions() -> None:
    request = CaseAnalysisRequest(
        case_title="合同争议",
        questions=["  是否完成交付？ ", "是否完成交付？"],
        materials=[CaseMaterial(title="合同", content="约定交货后付款。")],
    )

    assert request.questions == ["是否完成交付？"]


def test_request_rejects_materials_over_total_budget() -> None:
    with pytest.raises(ValidationError, match="total material content"):
        CaseAnalysisRequest(
            case_title="超长案件",
            materials=[
                CaseMaterial(title=f"材料 {index}", content="证" * 30_001)
                for index in range((MAX_TOTAL_MATERIAL_CHARS // 30_001) + 1)
            ],
        )

