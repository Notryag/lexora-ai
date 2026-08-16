from __future__ import annotations

from unittest.mock import Mock

import pytest

from lexora_ai.domain import LegalResearchDossier
from lexora_ai.infrastructure.legal_researcher import (
    LEGAL_RESEARCHER_TOOL,
    build_legal_researcher_subagent,
    partition_legal_research_tools,
)


def _tool(name: str) -> Mock:
    tool = Mock()
    tool.name = name
    return tool


def test_legal_researcher_has_a_bounded_reviewed_source_tool_surface() -> None:
    authority = _tool("search_legal_authorities")
    cases = _tool("search_guiding_cases")
    materials = _tool("search_case_materials")

    spec = build_legal_researcher_subagent([authority, cases, materials])

    assert spec.tool_name == LEGAL_RESEARCHER_TOOL
    assert spec.tools == (authority, cases)
    assert spec.skills == ()
    assert spec.result_schema is LegalResearchDossier
    assert spec.recursion_limit == 16
    assert "does not answer the user or update memory" in spec.description


def test_research_tools_are_removed_from_supervisor_surface() -> None:
    materials = _tool("search_case_materials")
    authority = _tool("search_legal_authorities")
    cases = _tool("search_guiding_cases")
    calculator = _tool("calculate_employment_termination_compensation")

    supervisor, researcher = partition_legal_research_tools(
        [materials, authority, cases, calculator]
    )

    assert [tool.name for tool in supervisor] == [
        "search_case_materials",
        "calculate_employment_termination_compensation",
    ]
    assert [tool.name for tool in researcher] == [
        "search_legal_authorities",
        "search_guiding_cases",
    ]


def test_research_dossier_preserves_only_source_references() -> None:
    dossier = LegalResearchDossier(
        coverage="partial",
        findings=[
            {
                "question": "违法解除赔偿标准",
                "conclusion": "违法解除时，赔偿金按经济补偿标准的二倍计算。",
                "references": ["Labc:C47", "Labc:C47"],
            }
        ],
        queries_used=["违法解除 赔偿金", "违法解除 赔偿金"],
        unresolved_questions=["当地高工资封顶基数"],
    )

    assert dossier.findings[0].references == ["Labc:C47"]
    assert dossier.queries_used == ["违法解除 赔偿金"]

    with pytest.raises(ValueError, match="legal or case-law reference"):
        LegalResearchDossier(
            coverage="partial",
            findings=[
                {
                    "question": "测试",
                    "conclusion": "测试",
                    "references": ["invented-reference"],
                }
            ],
        )
