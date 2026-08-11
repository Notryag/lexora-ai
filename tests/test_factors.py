from __future__ import annotations

from lexora_ai.domain import CaseFactorProfile, FactorSchemaRegistry


def test_factor_registry_matches_labor_domain() -> None:
    registry = FactorSchemaRegistry()

    domains, definitions = registry.definitions_for(
        case_type="劳动争议",
        legal_issue="解除劳动合同的经济补偿",
    )

    assert domains == ["labor.termination"]
    assert "labor.termination.reason" in {definition.key for definition in definitions}
    assert "core.procedural_stage" in {definition.key for definition in definitions}


def test_factor_registry_does_not_treat_all_criminal_cases_as_theft() -> None:
    registry = FactorSchemaRegistry()

    domains, _ = registry.definitions_for(
        case_type="刑事案件",
        legal_issue="故意伤害案件怎么处理？",
    )

    assert "criminal.theft" not in domains


def test_case_factor_profile_seeded_preserves_existing_values() -> None:
    registry = FactorSchemaRegistry()
    domains, definitions = registry.definitions_for(
        case_type="离婚财产分割",
        legal_issue="房产如何分割",
    )

    profile = CaseFactorProfile().seeded(domains=domains, definitions=definitions)
    updated = profile.seeded(domains=domains, definitions=definitions)

    assert updated.active_domains == ["family.divorce_property"]
    assert len(updated.factors) == len(profile.factors)
    assert "family.divorce_property.registration" in {factor.key for factor in updated.factors}
