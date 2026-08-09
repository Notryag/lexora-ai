from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lexora_ai.application import ConversationRetrievalPort


class LegalContextSearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=500,
        description="用于检索本案材料、已核验法规和已审核类案的具体法律问题",
    )


def build_legal_retrieval_tools(
    retrieval: ConversationRetrievalPort | None,
) -> list[StructuredTool]:
    if retrieval is None:
        return []

    async def search_case_materials(query: str) -> dict[str, object]:
        chunks = await retrieval.search_materials(query)
        return {
            "retrieved_material_chunks": [
                {
                    "reference": chunk.reference,
                    "material_id": chunk.material_id,
                    "title": chunk.title,
                    "kind": chunk.kind,
                    "source_note": chunk.source_note,
                    "content": chunk.content,
                }
                for chunk in chunks
            ]
        }

    async def search_legal_authorities(query: str) -> dict[str, object]:
        chunks = await retrieval.search_legal_authorities(query)
        return {
            "legal_authorities": [
                {
                    "reference": chunk.reference,
                    "title": chunk.title,
                    "article_label": chunk.article_label,
                    "issuing_authority": chunk.issuing_authority,
                    "source_url": chunk.source_url,
                    "status": chunk.status,
                    "content": chunk.content,
                }
                for chunk in chunks
            ]
        }

    async def search_guiding_cases(query: str) -> dict[str, object]:
        chunks = await retrieval.search_case_law(query)
        return {
            "case_law_authorities": [
                {
                    "reference": chunk.reference,
                    "case_number": chunk.case_number,
                    "title": chunk.title,
                    "section_label": chunk.section_label,
                    "issuing_authority": chunk.issuing_authority,
                    "source_url": chunk.source_url,
                    "published_on": chunk.published_on,
                    "content": chunk.content,
                }
                for chunk in chunks
            ]
        }

    return [
        StructuredTool.from_function(
            coroutine=search_case_materials,
            name="search_case_materials",
            description=(
                "Search only the user's submitted case materials for facts or evidence relevant "
                "to the current question. Do not call when no material verification is needed."
            ),
            args_schema=LegalContextSearchInput,
        ),
        StructuredTool.from_function(
            coroutine=search_legal_authorities,
            name="search_legal_authorities",
            description=(
                "Search only verified official statutes for legal rules relevant to the current "
                "question. Do not call for greetings, thanks, or non-legal conversation."
            ),
            args_schema=LegalContextSearchInput,
        ),
        StructuredTool.from_function(
            coroutine=search_guiding_cases,
            name="search_guiding_cases",
            description=(
                "Search only reviewed official guiding cases when a comparable-case analysis "
                "would materially help. Do not call for greetings or when statutes are sufficient."
            ),
            args_schema=LegalContextSearchInput,
        ),
    ]
