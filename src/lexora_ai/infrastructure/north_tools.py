from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lexora_ai.application import ConversationCaseMemoryPort, ConversationRetrievalPort
from lexora_ai.domain import (
    CaseFactorProfile,
    CaseProfile,
    CaseProfilePatch,
    FactorSchemaRegistry,
    LegalTurnFactorUpdate,
    LegalTurnIntent,
    LegalTurnPreparation,
    SufficiencyGate,
)
from lexora_ai.infrastructure.legal_turn_middleware import PREPARE_LEGAL_TURN_TOOL

_FACTOR_REGISTRY = FactorSchemaRegistry()
_SUFFICIENCY_GATE = SufficiencyGate()
_AUTHORITY_QUERY_LIMIT = 4
_AUTHORITY_SEARCH_CONCURRENCY = 2


class LegalContextSearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=500,
        description="用于检索本案材料、已核验法规和已审核类案的具体法律问题",
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


def _dedupe_chunks(chunks, *, limit: int):
    result = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk.reference in seen:
            continue
        seen.add(chunk.reference)
        result.append(chunk)
        if len(result) == limit:
            break
    return result


def _interleave_chunks(rankings, *, limit: int):
    """Merge ranked query results without letting one broad query consume the budget."""
    result = []
    seen: set[str] = set()
    max_ranking_length = max((len(ranking) for ranking in rankings), default=0)
    for rank in range(max_ranking_length):
        for ranking in rankings:
            if rank >= len(ranking):
                continue
            chunk = ranking[rank]
            if chunk.reference in seen:
                continue
            seen.add(chunk.reference)
            result.append(chunk)
            if len(result) == limit:
                return result
    return result


def _authority_queries(
    *,
    user_message: str,
    preparation: LegalTurnPreparation,
) -> list[str]:
    candidates = [
        user_message or preparation.legal_issue,
        *preparation.authority_queries,
    ]
    result: list[str] = []
    for candidate in candidates:
        normalized = (candidate or "").strip()[:500]
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) == _AUTHORITY_QUERY_LIMIT:
            break
    return result


async def _search_authority_queries(
    retrieval: ConversationRetrievalPort,
    queries: list[str],
):
    semaphore = asyncio.Semaphore(_AUTHORITY_SEARCH_CONCURRENCY)

    async def search(query: str):
        async with semaphore:
            return await retrieval.search_legal_authorities(query)

    return await asyncio.gather(*(search(query) for query in queries))


def _seed_factor_profile(
    profile: CaseProfile,
    preparation: LegalTurnPreparation,
) -> CaseFactorProfile:
    domains, definitions = _FACTOR_REGISTRY.definitions_for(
        case_type=preparation.case_type or profile.case_type,
        legal_issue=preparation.legal_issue,
    )
    return profile.factor_profile.seeded(domains=domains, definitions=definitions)


def _apply_factor_updates(
    profile: CaseFactorProfile,
    updates: list[LegalTurnFactorUpdate],
) -> CaseFactorProfile:
    return profile.apply_updates(updates)


def build_lexora_tools(
    retrieval: ConversationRetrievalPort | None,
    case_memory: ConversationCaseMemoryPort | None,
    *,
    user_message: str = "",
) -> list[StructuredTool]:
    tools: list[StructuredTool] = []

    async def prepare_legal_turn(
        intent: LegalTurnIntent,
        legal_issue: str | None = None,
        case_type: str | None = None,
        parties: list[str] | None = None,
        claims: list[str] | None = None,
        key_facts: list[str] | None = None,
        disputed_issues: list[str] | None = None,
        evidence_notes: list[str] | None = None,
        authority_queries: list[str] | None = None,
        material_query: str | None = None,
        case_law_query: str | None = None,
        decision_variables: list[str] | None = None,
        factor_updates: list[LegalTurnFactorUpdate] | None = None,
    ) -> dict[str, object]:
        preparation = LegalTurnPreparation(
            intent=intent,
            legal_issue=legal_issue,
            case_type=case_type,
            parties=parties or [],
            claims=claims or [],
            key_facts=key_facts or [],
            disputed_issues=disputed_issues or [],
            evidence_notes=evidence_notes or [],
            authority_queries=authority_queries or [],
            material_query=material_query,
            case_law_query=case_law_query,
            decision_variables=decision_variables or [],
            factor_updates=factor_updates or [],
        )

        profile: CaseProfile | None = None
        factor_profile_for_turn = CaseFactorProfile()
        if case_memory is not None and preparation.intent != LegalTurnIntent.social:
            profile = await case_memory.update_profile(
                CaseProfilePatch(
                    case_type=preparation.case_type,
                    parties=preparation.parties,
                    claims=preparation.claims,
                    key_facts=preparation.key_facts,
                    disputed_issues=preparation.disputed_issues,
                    evidence_notes=preparation.evidence_notes,
                    missing_information=preparation.decision_variables,
                )
            )
            factor_profile = _seed_factor_profile(profile, preparation)
            factor_profile = _apply_factor_updates(
                factor_profile,
                preparation.factor_updates,
            )
            factor_profile_for_turn = factor_profile
            if factor_profile != profile.factor_profile:
                profile = await case_memory.update_profile(
                    CaseProfilePatch(factor_profile=factor_profile)
                )
        elif preparation.intent != LegalTurnIntent.social:
            factor_profile_for_turn = _apply_factor_updates(
                _seed_factor_profile(CaseProfile(), preparation),
                preparation.factor_updates,
            )

        legal_rankings = []
        material_chunks = []
        case_law_chunks = []
        executed_queries: list[str] = []
        if preparation.intent == LegalTurnIntent.legal_question and retrieval is not None:
            executed_queries = _authority_queries(
                user_message=user_message,
                preparation=preparation,
            )
            legal_rankings = await _search_authority_queries(retrieval, executed_queries)
            if preparation.material_query:
                material_chunks.extend(await retrieval.search_materials(preparation.material_query))
            if preparation.case_law_query:
                case_law_chunks.extend(await retrieval.search_case_law(preparation.case_law_query))

        legal_chunks = _interleave_chunks(legal_rankings, limit=12)
        material_chunks = _dedupe_chunks(material_chunks, limit=8)
        case_law_chunks = _dedupe_chunks(case_law_chunks, limit=6)
        sufficiency = _SUFFICIENCY_GATE.evaluate(
            intent=preparation.intent,
            factor_profile=(
                profile.factor_profile if profile is not None else factor_profile_for_turn
            ),
            decision_variables=preparation.decision_variables,
        )
        return {
            "turn_preparation": {
                "intent": preparation.intent.value,
                "legal_issue": preparation.legal_issue,
                "user_stated_facts": preparation.key_facts,
                "decision_variables": preparation.decision_variables,
                "factor_domains": (
                    profile.factor_profile.active_domains
                    if profile is not None
                    else factor_profile_for_turn.active_domains
                ),
                "factor_updates": [
                    factor_update.model_dump(mode="json")
                    for factor_update in preparation.factor_updates
                ],
                "authority_queries": executed_queries,
                "authority_query_coverage": [
                    {
                        "query": query,
                        "references": [chunk.reference for chunk in ranking[:3]],
                    }
                    for query, ranking in zip(
                        executed_queries,
                        legal_rankings,
                        strict=True,
                    )
                ],
            },
            "case_profile": profile.model_dump(mode="json") if profile is not None else None,
            "legal_authorities": [_legal_chunk_payload(chunk) for chunk in legal_chunks],
            "retrieved_material_chunks": [
                _material_chunk_payload(chunk) for chunk in material_chunks
            ],
            "case_law_authorities": [_case_law_chunk_payload(chunk) for chunk in case_law_chunks],
            "response_contract": {
                "answer_current_question_first": sufficiency.answer_now,
                "maximum_follow_up_questions": len(sufficiency.follow_up_questions),
                "exact_outcome_prediction_allowed": False,
                "separate_known_facts_from_conditions": True,
                "follow_up_questions": [
                    question.model_dump(mode="json") for question in sufficiency.follow_up_questions
                ],
            },
        }

    tools.append(
        StructuredTool.from_function(
            coroutine=prepare_legal_turn,
            name=PREPARE_LEGAL_TURN_TOOL,
            description=(
                "Prepare every Lexora conversation turn before answering. Classify the turn as "
                "social, case_update, or legal_question. Copy only facts explicitly stated by the "
                "user; never place legal conclusions in key_facts. For a legal question, identify "
                "one legal_issue, provide up to three focused authority_queries covering the "
                "governing rule and outcome-changing factors, and at most two decision_variables. "
                "When factor_schema is present in case_data, emit factor_updates using only those "
                "factor keys and only for user-stated or user-denied facts from the current turn. "
                "The tool stages case memory and performs the required retrieval as one structured "
                "step. Use material_query or case_law_query only when those sources would materially "
                "help. Do not answer the user until this tool returns."
            ),
            args_schema=LegalTurnPreparation,
        )
    )

    async def search_case_materials(query: str) -> dict[str, object]:
        chunks = await retrieval.search_materials(query)
        return {"retrieved_material_chunks": [_material_chunk_payload(chunk) for chunk in chunks]}

    async def search_legal_authorities(query: str) -> dict[str, object]:
        chunks = await retrieval.search_legal_authorities(query)
        return {"legal_authorities": [_legal_chunk_payload(chunk) for chunk in chunks]}

    async def search_guiding_cases(query: str) -> dict[str, object]:
        chunks = await retrieval.search_case_law(query)
        return {"case_law_authorities": [_case_law_chunk_payload(chunk) for chunk in chunks]}

    if retrieval is not None:
        tools.extend(
            [
                StructuredTool.from_function(
                    coroutine=search_case_materials,
                    name="search_case_materials",
                    description=(
                        "Supplement the prepared turn by searching only the user's submitted case "
                        "materials. Do not call before prepare_legal_turn."
                    ),
                    args_schema=LegalContextSearchInput,
                ),
                StructuredTool.from_function(
                    coroutine=search_legal_authorities,
                    name="search_legal_authorities",
                    description=(
                        "Supplement the prepared turn with a more specific search of reviewed "
                        "official statutes. Do not call before prepare_legal_turn."
                    ),
                    args_schema=LegalContextSearchInput,
                ),
                StructuredTool.from_function(
                    coroutine=search_guiding_cases,
                    name="search_guiding_cases",
                    description=(
                        "Supplement the prepared turn with reviewed official guiding cases only "
                        "when comparison would materially help."
                    ),
                    args_schema=LegalContextSearchInput,
                ),
            ]
        )

    return tools
