from __future__ import annotations

import pytest

from lexora_ai.domain import LegalTurnAssessment
from lexora_ai.infrastructure.case_analyst import (
    CASE_ANALYST_TOOL,
    build_case_analyst_subagent,
)


def test_case_analyst_is_bounded_and_structured() -> None:
    spec = build_case_analyst_subagent()

    assert spec.tool_name == CASE_ANALYST_TOOL
    assert spec.tools == ()
    assert spec.skills == ()
    assert spec.result_schema is LegalTurnAssessment
    assert "does not research or answer" in spec.description


def test_social_assessment_rejects_case_payload() -> None:
    with pytest.raises(ValueError, match="social turns cannot contain case analysis"):
        LegalTurnAssessment(
            intent="social",
            key_facts=["用户咨询劳动合同解除"],
        )


def test_case_assessment_preserves_atomic_denial() -> None:
    assessment = LegalTurnAssessment(
        intent="legal_question",
        legal_issue="是否构成重婚",
        answer_targets=[
            {
                "question": "没有以夫妻名义同居是否构成重婚？",
                "mode": "direct",
                "kind": "classification",
            }
        ],
        key_facts=["没有以夫妻名义同居"],
        factor_updates=[
            {
                "key": "relationship.holds_out_as_spouses",
                "label": "是否以夫妻身份生活",
                "type": "boolean",
                "state": "asserted",
                "value": False,
                "materiality": "high",
            }
        ],
    )

    assert assessment.factor_updates[0].state == "denied"
    assert assessment.factor_updates[0].value is False
