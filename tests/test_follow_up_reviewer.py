from __future__ import annotations

from pydantic import SecretStr

from lexora_ai.config import Settings
from lexora_ai.domain import (
    CaseFactor,
    CaseFactorProfile,
    FactorMateriality,
    FactorType,
    LegalTurnAnswerKind,
    LegalTurnAnswerMode,
    LegalTurnAnswerTarget,
    LegalTurnContextStatus,
    LegalTurnFactorGroundingStatus,
    LegalTurnFactorUpdate,
    LegalTurnFollowUpCandidate,
    LegalTurnFollowUpImpact,
    LegalTurnIntent,
    LegalTurnPreparation,
)
from lexora_ai.infrastructure.follow_up_reviewer import NorthFollowUpReviewer


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def chat(self, _prompt: str, *, thread_id: str) -> str:
        assert thread_id
        return self.response


def _preparation() -> LegalTurnPreparation:
    return LegalTurnPreparation(
        intent=LegalTurnIntent.legal_question,
        legal_issue="盗窃量刑区间",
        answer_targets=[
            LegalTurnAnswerTarget(
                question="大概会判多久？",
                mode=LegalTurnAnswerMode.conditional,
                kind=LegalTurnAnswerKind.estimate,
            )
        ],
        follow_up_candidates=[
            LegalTurnFollowUpCandidate(
                factor_key="criminal.prior_sentence_completion",
                answer_target_index=0,
                impact=LegalTurnFollowUpImpact.legal_range,
                reason="可能影响是否构成累犯。",
            )
        ],
    )


def _reviewer(response: str) -> NorthFollowUpReviewer:
    reviewer = NorthFollowUpReviewer(Settings(openai_api_key=SecretStr("test")))
    reviewer._client = FakeClient(response)  # type: ignore[assignment]
    return reviewer


def _factor_reviewer(response: str) -> NorthFollowUpReviewer:
    reviewer = NorthFollowUpReviewer(Settings(openai_api_key=SecretStr("test")))
    reviewer._factor_client = FakeClient(response)  # type: ignore[assignment]
    return reviewer


async def test_follow_up_reviewer_parses_complete_structured_result() -> None:
    reviewer = _reviewer(
        '{"reviews":[{"factor_key":"criminal.prior_sentence_completion",'
        '"context_status":"unresolved","context_basis":"用户没有说明执行完毕时间。"}]}'
    )

    reviews = await reviewer.review(
        user_message="他以前被判过刑，这次盗窃大概判多久？",
        preparation=_preparation(),
        factor_profile=CaseFactorProfile(
            factors=[
                CaseFactor(
                    key="criminal.prior_sentence_completion",
                    label="前罪执行完毕时间",
                    type=FactorType.text,
                    materiality=FactorMateriality.high,
                    question="前罪何时执行完毕？",
                )
            ]
        ),
    )

    assert reviews[0].context_status == LegalTurnContextStatus.unresolved


async def test_follow_up_reviewer_suppresses_candidates_on_invalid_output() -> None:
    reviewer = _reviewer("not json")

    reviews = await reviewer.review(
        user_message="大概会判多久？",
        preparation=_preparation(),
        factor_profile=CaseFactorProfile(),
    )

    assert reviews[0].context_status == LegalTurnContextStatus.partially_resolved


async def test_factor_reviewer_rejects_a_broader_denial_than_the_user_stated() -> None:
    preparation = _preparation().model_copy(
        update={
            "factor_updates": [
                LegalTurnFactorUpdate(
                    key="cohabitation.present",
                    label="是否共同生活",
                    type="boolean",
                    state="denied",
                    value=False,
                    materiality="high",
                )
            ]
        }
    )
    reviewer = _factor_reviewer(
        '{"reviews":[{"factor_key":"cohabitation.present",'
        '"status":"overbroad","context_basis":"原话只否定以夫妻名义同居。"}]}'
    )

    reviews = await reviewer.review_factor_updates(
        user_message="我们没有以夫妻名义同居。",
        preparation=preparation,
        factor_profile=CaseFactorProfile(),
    )

    assert reviews[0].status == LegalTurnFactorGroundingStatus.overbroad


async def test_factor_reviewer_suppresses_claimed_updates_on_invalid_output() -> None:
    preparation = _preparation().model_copy(
        update={
            "factor_updates": [
                LegalTurnFactorUpdate(
                    key="relationship.holds_out_as_spouses",
                    label="是否以夫妻身份生活",
                    type="boolean",
                    state="denied",
                    value=False,
                    materiality="high",
                )
            ]
        }
    )
    reviewer = _factor_reviewer("not json")

    reviews = await reviewer.review_factor_updates(
        user_message="我们没有以夫妻名义同居。",
        preparation=preparation,
        factor_profile=CaseFactorProfile(),
    )

    assert reviews[0].status == LegalTurnFactorGroundingStatus.unsupported
