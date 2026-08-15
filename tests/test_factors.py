from __future__ import annotations

from lexora_ai.domain import CaseFactorProfile, FactorState, LegalTurnFactorUpdate


def test_factor_profile_accepts_ai_discovered_factor() -> None:
    profile = CaseFactorProfile().apply_updates(
        [
            LegalTurnFactorUpdate(
                key="relationship.holds_out_as_spouses",
                label="是否以夫妻身份生活",
                type="boolean",
                state="denied",
                value=False,
                materiality="high",
                question="双方是否曾对外以夫妻身份生活？",
            )
        ]
    )

    assert len(profile.factors) == 1
    assert profile.factors[0].key == "relationship.holds_out_as_spouses"
    assert profile.factors[0].state == "denied"
    assert profile.factors[0].value is False


def test_boolean_factor_state_is_normalized_from_explicit_value() -> None:
    denied = LegalTurnFactorUpdate(
        key="relationship.holds_out_as_spouses",
        label="是否以夫妻身份生活",
        type="boolean",
        state="asserted",
        value=False,
        materiality="high",
    )
    conflicting = LegalTurnFactorUpdate(
        key="relationship.holds_out_as_spouses",
        label="是否以夫妻身份生活",
        type="boolean",
        state="denied",
        value=True,
        materiality="high",
    )

    assert denied.state == FactorState.denied
    assert conflicting.state == FactorState.conflicting


def test_factor_profile_reuses_existing_key_without_duplicate() -> None:
    first = LegalTurnFactorUpdate(
        key="employment.service_years",
        label="工作年限",
        type="numeric",
        state="unknown",
        materiality="high",
        question="你在公司工作了多久？",
    )
    profile = CaseFactorProfile().apply_updates([first])

    updated = profile.apply_updates(
        [
            LegalTurnFactorUpdate(
                key="employment.service_years",
                label="工作年限",
                type="numeric",
                state="asserted",
                value=4,
                materiality="high",
            )
        ]
    )

    assert len(updated.factors) == 1
    assert updated.factors[0].value == 4
    assert updated.factors[0].question == "你在公司工作了多久？"
