from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from lexora_ai.application import (
    ConversationCaseMemoryPort,
    ConversationRetrievalPort,
    FactorUpdateReviewerPort,
    FollowUpReviewerPort,
)
from lexora_ai.domain import (
    CaseFactorProfile,
    CaseProfile,
    CaseProfilePatch,
    FactorState,
    LegalTurnAnswerKind,
    LegalTurnAnswerTarget,
    LegalTurnContextStatus,
    LegalTurnFactorGroundingReview,
    LegalTurnFactorGroundingStatus,
    LegalTurnFactorUpdate,
    LegalTurnFollowUpCandidate,
    LegalTurnFollowUpReview,
    LegalTurnIntent,
    LegalTurnPreparation,
    SufficiencyGate,
)
from lexora_ai.infrastructure.legal_turn_middleware import PREPARE_LEGAL_TURN_TOOL

_SUFFICIENCY_GATE = SufficiencyGate()
_AUTHORITY_QUERY_LIMIT = 4
_AUTHORITY_SEARCH_CONCURRENCY = 2
_FOLLOW_UP_ELIGIBLE_ANSWER_KINDS = {
    LegalTurnAnswerKind.estimate,
    LegalTurnAnswerKind.calculation,
    LegalTurnAnswerKind.action,
}


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


def _apply_factor_updates(
    profile: CaseFactorProfile,
    updates: list[LegalTurnFactorUpdate],
) -> CaseFactorProfile:
    return profile.apply_updates(updates)


def _profile_for_commit(
    profile: CaseFactorProfile,
    admitted_factor_keys: set[str],
) -> CaseFactorProfile:
    committed = profile.model_copy(deep=True)
    committed.factors = [
        factor
        for factor in committed.factors
        if factor.state != FactorState.unknown or factor.key in admitted_factor_keys
    ]
    return committed


def build_lexora_tools(
    retrieval: ConversationRetrievalPort | None,
    case_memory: ConversationCaseMemoryPort | None,
    *,
    user_message: str = "",
    jurisdiction: str = "中国大陆",
    follow_up_reviewer: FollowUpReviewerPort | None = None,
    factor_update_reviewer: FactorUpdateReviewerPort | None = None,
) -> list[StructuredTool]:
    tools: list[StructuredTool] = []

    def response_contract(
        preparation: LegalTurnPreparation,
        questions,
        factor_profile: CaseFactorProfile,
    ) -> dict[str, object]:
        known_factors = [
            factor for factor in factor_profile.factors if factor.state != FactorState.unknown
        ]
        return {
            "answer_current_question_first": True,
            "jurisdiction": jurisdiction,
            "jurisdiction_confirmation_required": False,
            "answer_targets": [
                target.model_dump(mode="json") for target in preparation.answer_targets
            ],
            "maximum_follow_up_questions": len(questions),
            "exact_outcome_prediction_allowed": False,
            "separate_known_facts_from_conditions": True,
            "do_not_reask_known_facts": True,
            "do_not_introduce_hypotheticals_contrary_to_known_facts": True,
            "known_factor_constraints": [
                {
                    "key": factor.key,
                    "label": factor.label,
                    "state": factor.state.value,
                    "value": factor.value,
                }
                for factor in known_factors
            ],
            "prohibited_counterfactual_factor_keys": [
                factor.key
                for factor in known_factors
                if factor.state == FactorState.denied or factor.value is False
            ],
            "follow_up_questions": [
                question.model_dump(mode="json") for question in questions
            ],
        }

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
        answer_targets: list[LegalTurnAnswerTarget] | None = None,
        follow_up_candidates: list[LegalTurnFollowUpCandidate] | None = None,
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
            answer_targets=answer_targets or [],
            follow_up_candidates=follow_up_candidates or [],
            factor_updates=factor_updates or [],
        )

        profile: CaseProfile | None = None
        factor_grounding_reviews: list[LegalTurnFactorGroundingReview] = []
        accepted_factor_updates = list(preparation.factor_updates)
        factor_profile_for_turn = CaseFactorProfile()
        if case_memory is not None and preparation.intent != LegalTurnIntent.social:
            current_profile = await case_memory.get_profile()
            if factor_update_reviewer is not None:
                factor_grounding_reviews = await factor_update_reviewer.review_factor_updates(
                    user_message=user_message,
                    preparation=preparation,
                    factor_profile=current_profile.factor_profile,
                )
                accepted_factor_keys = {
                    review.factor_key
                    for review in factor_grounding_reviews
                    if review.status == LegalTurnFactorGroundingStatus.grounded
                }
                accepted_factor_updates = [
                    update
                    for update in preparation.factor_updates
                    if update.state == FactorState.unknown
                    or update.key in accepted_factor_keys
                ]
            factor_profile_for_turn = _apply_factor_updates(
                current_profile.factor_profile,
                accepted_factor_updates,
            )
        elif preparation.intent != LegalTurnIntent.social:
            factor_profile_for_turn = _apply_factor_updates(
                CaseFactorProfile(),
                accepted_factor_updates,
            )

        reviews: list[LegalTurnFollowUpReview] = []
        review_needed = any(
            preparation.answer_targets[candidate.answer_target_index].kind
            in _FOLLOW_UP_ELIGIBLE_ANSWER_KINDS
            for candidate in preparation.follow_up_candidates
        )
        if review_needed:
            if follow_up_reviewer is not None:
                reviews = await follow_up_reviewer.review(
                    user_message=user_message,
                    preparation=preparation,
                    factor_profile=factor_profile_for_turn,
                )
            else:
                reviews = [
                    LegalTurnFollowUpReview(
                        factor_key=candidate.factor_key,
                        context_status=LegalTurnContextStatus.partially_resolved,
                        context_basis="追问审核器未配置，本轮保守地不追加问题。",
                    )
                    for candidate in preparation.follow_up_candidates
                ]
        sufficiency = _SUFFICIENCY_GATE.evaluate(
            intent=preparation.intent,
            factor_profile=factor_profile_for_turn,
            answer_targets=preparation.answer_targets,
            follow_up_candidates=preparation.follow_up_candidates,
            follow_up_reviews=reviews,
        )
        if case_memory is not None and preparation.intent != LegalTurnIntent.social:
            admitted_factor_keys = {
                question.factor_key
                for question in sufficiency.follow_up_questions
                if question.factor_key is not None
            }
            profile = await case_memory.update_profile(
                CaseProfilePatch(
                    case_type=preparation.case_type,
                    parties=preparation.parties,
                    claims=preparation.claims,
                    key_facts=preparation.key_facts,
                    disputed_issues=preparation.disputed_issues,
                    evidence_notes=preparation.evidence_notes,
                    missing_information=[
                        question.question for question in sufficiency.follow_up_questions
                    ],
                    factor_profile=_profile_for_commit(
                        factor_profile_for_turn,
                        admitted_factor_keys,
                    ),
                )
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
        return {
            "turn_preparation": {
                "intent": preparation.intent.value,
                "legal_issue": preparation.legal_issue,
                "user_stated_facts": preparation.key_facts,
                "answer_targets": [
                    target.model_dump(mode="json") for target in preparation.answer_targets
                ],
                "follow_up_candidates": [
                    candidate.model_dump(mode="json")
                    for candidate in preparation.follow_up_candidates
                ],
                "follow_up_review": [
                    review.model_dump(mode="json") for review in reviews
                ],
                "factor_updates": [
                    factor_update.model_dump(mode="json")
                    for factor_update in accepted_factor_updates
                ],
                "factor_grounding_review": [
                    review.model_dump(mode="json")
                    for review in factor_grounding_reviews
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
            "response_contract": response_contract(
                preparation,
                sufficiency.follow_up_questions,
                factor_profile_for_turn,
            ),
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
                "governing rule and outcome-changing factual dimensions. Autonomously extract a "
                "small structured factor set: create stable semantic keys with neutral labels, "
                "types, materiality, and canonical questions; reuse the exact key already present "
                "in case_profile whenever the dimension exists. A factor is a case fact, never a "
                "legal conclusion, prediction, statute, or generic warning. Use asserted or denied "
                "only for facts explicit in the current user turn. Preserve every qualifier and "
                "the exact scope of a negation; a qualified denial cannot become a broader denial. "
                "Use unknown only for facts that "
                "would materially change the current answer. Restate every question the user "
                "actually asked in answer_targets and choose direct or conditional response mode. "
                "Classify each target as rule, classification, estimate, calculation, or action. "
                "Rule explanations and classifications must be answered with bounded branches and "
                "do not trigger automatic follow-up questions. "
                "Propose follow_up_candidates only when the answer could change liability, the legal "
                "range, an amount, or the user's next action. The application admits at most two "
                "high-materiality unknown factors after a separate context review. "
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
