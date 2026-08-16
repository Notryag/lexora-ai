from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lexora_ai.application import ConversationRetrievalPort
from lexora_ai.domain.legal_calculations import (
    EmploymentTerminationCompensationInput,
    calculate_employment_termination_compensation,
)

_MATERIAL_SEARCH_LIMIT = 3
_LEGAL_AUTHORITY_SEARCH_LIMIT = 5
_CASE_LAW_SEARCH_LIMIT = 2


class LegalContextSearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=500,
        description="用于检索本案材料、已核验法规或已审核类案的具体问题",
    )


def _legal_chunk_payload(chunk) -> dict[str, object]:
    return {
        "reference": chunk.reference,
        "title": chunk.title,
        "article_label": chunk.article_label,
        "issuing_authority": chunk.issuing_authority,
        "source_url": chunk.source_url,
        "status": chunk.status,
        "content": chunk.content,
    }


def _material_chunk_payload(chunk) -> dict[str, object]:
    return {
        "reference": chunk.reference,
        "material_id": chunk.material_id,
        "title": chunk.title,
        "kind": chunk.kind,
        "source_note": chunk.source_note,
        "content": chunk.content,
    }


def _case_law_chunk_payload(chunk) -> dict[str, object]:
    return {
        "reference": chunk.reference,
        "case_number": chunk.case_number,
        "title": chunk.title,
        "section_label": chunk.section_label,
        "issuing_authority": chunk.issuing_authority,
        "source_url": chunk.source_url,
        "published_on": chunk.published_on,
        "content": chunk.content,
    }


def build_lexora_tools(
    retrieval: ConversationRetrievalPort | None,
) -> list[StructuredTool]:
    def calculate_termination_compensation(
        completed_years: int,
        additional_months: int,
        monthly_wage,
        local_average_monthly_wage=None,
    ) -> dict[str, object]:
        return calculate_employment_termination_compensation(
            EmploymentTerminationCompensationInput(
                completed_years=completed_years,
                additional_months=additional_months,
                monthly_wage=monthly_wage,
                local_average_monthly_wage=local_average_monthly_wage,
            )
        )

    tools = [
        StructuredTool.from_function(
            func=calculate_termination_compensation,
            name="calculate_employment_termination_compensation",
            description=(
                "Calculate mainland China employment-termination N and 2N amounts from service "
                "duration and average monthly wage. Use only after sourced research establishes "
                "the applicable legal branch. The tool performs arithmetic, not legal judgment."
            ),
            args_schema=EmploymentTerminationCompensationInput,
        )
    ]
    if retrieval is None:
        return tools

    material_searches = 0
    legal_authority_searches = 0
    case_law_searches = 0

    async def search_case_materials(query: str) -> dict[str, object]:
        nonlocal material_searches
        if material_searches >= _MATERIAL_SEARCH_LIMIT:
            return {
                "retrieved_material_chunks": [],
                "search_limit_reached": True,
                "remaining_searches": 0,
            }
        material_searches += 1
        chunks = await retrieval.search_materials(query)
        return {
            "retrieved_material_chunks": [
                _material_chunk_payload(chunk) for chunk in chunks
            ],
            "search_limit_reached": False,
            "remaining_searches": _MATERIAL_SEARCH_LIMIT - material_searches,
        }

    async def search_legal_authorities(query: str) -> dict[str, object]:
        nonlocal legal_authority_searches
        if legal_authority_searches >= _LEGAL_AUTHORITY_SEARCH_LIMIT:
            return {
                "legal_authorities": [],
                "search_limit_reached": True,
                "remaining_searches": 0,
            }
        legal_authority_searches += 1
        chunks = await retrieval.search_legal_authorities(query)
        return {
            "legal_authorities": [_legal_chunk_payload(chunk) for chunk in chunks],
            "search_limit_reached": False,
            "remaining_searches": (
                _LEGAL_AUTHORITY_SEARCH_LIMIT - legal_authority_searches
            ),
        }

    async def search_guiding_cases(query: str) -> dict[str, object]:
        nonlocal case_law_searches
        if case_law_searches >= _CASE_LAW_SEARCH_LIMIT:
            return {
                "case_law_authorities": [],
                "search_limit_reached": True,
                "remaining_searches": 0,
            }
        case_law_searches += 1
        chunks = await retrieval.search_case_law(query)
        return {
            "case_law_authorities": [
                _case_law_chunk_payload(chunk) for chunk in chunks
            ],
            "search_limit_reached": False,
            "remaining_searches": _CASE_LAW_SEARCH_LIMIT - case_law_searches,
        }

    tools.extend(
        [
            StructuredTool.from_function(
                coroutine=search_case_materials,
                name="search_case_materials",
                description=(
                    "Search only the user's submitted case materials for one focused factual "
                    "question. At most three searches are accepted in one turn."
                ),
                args_schema=LegalContextSearchInput,
            ),
            StructuredTool.from_function(
                coroutine=search_legal_authorities,
                name="search_legal_authorities",
                description=(
                    "Search reviewed official statutes for one focused legal question. At most "
                    "five searches are accepted in one turn."
                ),
                args_schema=LegalContextSearchInput,
            ),
            StructuredTool.from_function(
                coroutine=search_guiding_cases,
                name="search_guiding_cases",
                description=(
                    "Search reviewed official case law, including guiding, reference, and typical "
                    "cases, for one focused comparison. At most two searches are accepted in one "
                    "turn."
                ),
                args_schema=LegalContextSearchInput,
            ),
        ]
    )
    return tools
