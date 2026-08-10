from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lexora_ai.application import ConversationCaseMemoryPort, ConversationRetrievalPort
from lexora_ai.domain import CaseProfilePatch


class LegalContextSearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=500,
        description="用于检索本案材料、已核验法规和已审核类案的具体法律问题",
    )


def build_lexora_tools(
    retrieval: ConversationRetrievalPort | None,
    case_memory: ConversationCaseMemoryPort | None,
) -> list[StructuredTool]:
    tools: list[StructuredTool] = []

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

    if retrieval is not None:
        tools.extend(
            [
                StructuredTool.from_function(
                    coroutine=search_case_materials,
                    name="search_case_materials",
                    description=(
                        "Search only the user's submitted case materials for facts or evidence "
                        "relevant to the current question. Do not call when no material "
                        "verification is needed."
                    ),
                    args_schema=LegalContextSearchInput,
                ),
                StructuredTool.from_function(
                    coroutine=search_legal_authorities,
                    name="search_legal_authorities",
                    description=(
                        "Search only verified official statutes for legal rules relevant to the "
                        "current question. Cite only the smallest set actually used in the answer. "
                        "Do not call for greetings, thanks, or non-legal conversation."
                    ),
                    args_schema=LegalContextSearchInput,
                ),
                StructuredTool.from_function(
                    coroutine=search_guiding_cases,
                    name="search_guiding_cases",
                    description=(
                        "Search only reviewed official guiding cases when a comparable-case "
                        "analysis would materially help. Do not call for greetings, broad "
                        "preliminary questions, or when statutes are sufficient."
                    ),
                    args_schema=LegalContextSearchInput,
                ),
            ]
        )

    if case_memory is not None:
        async def update_case_profile(
            case_type: str | None = None,
            parties: list[str] | None = None,
            claims: list[str] | None = None,
            key_facts: list[str] | None = None,
            disputed_issues: list[str] | None = None,
            evidence_notes: list[str] | None = None,
            missing_information: list[str] | None = None,
            resolved_missing_information: list[str] | None = None,
        ) -> dict[str, object]:
            profile = await case_memory.update_profile(
                CaseProfilePatch(
                    case_type=case_type,
                    parties=parties or [],
                    claims=claims or [],
                    key_facts=key_facts or [],
                    disputed_issues=disputed_issues or [],
                    evidence_notes=evidence_notes or [],
                    missing_information=missing_information,
                    resolved_missing_information=resolved_missing_information or [],
                )
            )
            return {"case_profile": profile.model_dump(mode="json")}

        tools.append(
            StructuredTool.from_function(
                coroutine=update_case_profile,
                name="update_case_profile",
                description=(
                    "Stage only information not already represented with the same meaning in the "
                    "current Lexora case profile. Before the final answer, call when the current "
                    "turn establishes a case type, party, claim, explicit fact, issue, evidence "
                    "lead, resolves missing information, or the answer asks for new critical "
                    "missing information. When asking questions, replace missing_information with "
                    "the complete deduplicated list still unanswered after this turn. Never call "
                    "for paraphrases or repeated confirmations of "
                    "existing profile facts. One statement may update multiple fields: when a user "
                    "explicitly names themself, a spouse, a company, or another participant, add "
                    "the participant to parties even when the same statement is also a key fact. "
                    "Never store legal conclusions, model inferences, retrieved authority text, "
                    "or greetings."
                ),
                args_schema=CaseProfilePatch,
            )
        )

    return tools
