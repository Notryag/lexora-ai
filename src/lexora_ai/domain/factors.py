from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class FactorType(StrEnum):
    text = "text"
    numeric = "numeric"
    boolean = "boolean"
    categorical = "categorical"


class FactorState(StrEnum):
    asserted = "asserted"
    denied = "denied"
    unknown = "unknown"
    conflicting = "conflicting"


class FactorMateriality(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class FactorDefinition(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    type: FactorType
    question: str = Field(min_length=1, max_length=300)
    materiality: FactorMateriality = FactorMateriality.medium
    options: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("key", "label", "question")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result


class CaseFactor(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    type: FactorType
    state: FactorState = FactorState.unknown
    value: bool | int | float | str | None = None
    materiality: FactorMateriality = FactorMateriality.medium
    question: str | None = Field(default=None, max_length=300)
    source_turns: list[int] = Field(default_factory=list, max_length=20)
    source_material_refs: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("key", "label", "question", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("source_turns")
    @classmethod
    def normalize_turns(cls, value: list[int]) -> list[int]:
        result: list[int] = []
        for item in value:
            if item not in result:
                result.append(item)
        return result

    @field_validator("source_material_refs")
    @classmethod
    def normalize_refs(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result


class CaseFactorProfile(BaseModel):
    active_domains: list[str] = Field(default_factory=list, max_length=8)
    factors: list[CaseFactor] = Field(default_factory=list, max_length=80)

    @field_validator("active_domains")
    @classmethod
    def normalize_domains(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            text = item.strip()
            if text and text not in result:
                result.append(text)
        return result

    def seeded(
        self,
        *,
        domains: list[str],
        definitions: list[FactorDefinition],
    ) -> CaseFactorProfile:
        profile = self.model_copy(deep=True)
        for domain in domains:
            if domain not in profile.active_domains:
                profile.active_domains.append(domain)
        existing = {factor.key: factor for factor in profile.factors}
        for definition in definitions:
            if definition.key in existing:
                continue
            profile.factors.append(
                CaseFactor(
                    key=definition.key,
                    label=definition.label,
                    type=definition.type,
                    state=FactorState.unknown,
                    materiality=definition.materiality,
                    question=definition.question,
                )
            )
        return profile

    def retrieval_text(self) -> str:
        values = [*self.active_domains]
        for factor in self.factors:
            if factor.state == FactorState.unknown:
                continue
            if factor.value is None:
                values.append(factor.label)
                continue
            values.append(f"{factor.label}:{factor.value}")
        return " ".join(value for value in values if value)

    def apply_updates(
        self,
        updates: list[object],
    ) -> CaseFactorProfile:
        from lexora_ai.domain.legal_turns import LegalTurnFactorUpdate

        profile = self.model_copy(deep=True)
        by_key = {factor.key: factor for factor in profile.factors}
        for update in updates:
            if not isinstance(update, LegalTurnFactorUpdate):
                update = LegalTurnFactorUpdate.model_validate(update)
            factor = by_key.get(update.key)
            if factor is None:
                continue
            factor.state = update.state
            factor.value = update.value
        return profile


class FactorSchemaRegistry:
    def __init__(self) -> None:
        self._core = (
            FactorDefinition(
                key="core.jurisdiction",
                label="适用法域",
                type=FactorType.text,
                question="案件发生在哪个国家或地区，准备适用哪里的法律？",
                materiality=FactorMateriality.high,
            ),
            FactorDefinition(
                key="core.procedural_stage",
                label="当前阶段",
                type=FactorType.categorical,
                question="目前处于协商、报警、立案、仲裁、起诉、一审、二审还是执行阶段？",
                materiality=FactorMateriality.high,
            ),
            FactorDefinition(
                key="core.timeline",
                label="关键时间线",
                type=FactorType.text,
                question="关键事情分别发生在什么时间？",
                materiality=FactorMateriality.high,
            ),
            FactorDefinition(
                key="core.evidence",
                label="证据线索",
                type=FactorType.text,
                question="目前手里有哪些材料、记录或可取得的证据？",
                materiality=FactorMateriality.medium,
            ),
        )
        self._domains = {
            "criminal.theft": (
                FactorDefinition(
                    key="criminal.theft.amount",
                    label="盗窃金额",
                    type=FactorType.numeric,
                    question="涉案金额大致是多少，是否已有鉴定或价格认定？",
                    materiality=FactorMateriality.high,
                ),
                FactorDefinition(
                    key="criminal.theft.residential_entry",
                    label="是否入户盗窃",
                    type=FactorType.boolean,
                    question="是否进入供家庭生活、相对隔离的住所实施盗窃？",
                    materiality=FactorMateriality.high,
                ),
                FactorDefinition(
                    key="criminal.theft.prior_conviction",
                    label="前科及累犯相关情况",
                    type=FactorType.text,
                    question="前罪判了什么、何时执行完毕，距本次行为是否不满五年？",
                    materiality=FactorMateriality.high,
                ),
            ),
            "labor.termination": (
                FactorDefinition(
                    key="labor.termination.reason",
                    label="解除理由",
                    type=FactorType.text,
                    question="公司或劳动者提出解除的理由是什么？",
                    materiality=FactorMateriality.high,
                ),
                FactorDefinition(
                    key="labor.termination.service_years",
                    label="工作年限",
                    type=FactorType.numeric,
                    question="一共工作了多久？",
                    materiality=FactorMateriality.high,
                ),
                FactorDefinition(
                    key="labor.termination.salary_base",
                    label="工资基数",
                    type=FactorType.numeric,
                    question="离职前十二个月平均工资大约是多少？",
                    materiality=FactorMateriality.high,
                ),
            ),
            "family.divorce_property": (
                FactorDefinition(
                    key="family.divorce_property.acquisition_time",
                    label="房产取得时间",
                    type=FactorType.text,
                    question="房产是在婚前还是婚后购买、取得的？",
                    materiality=FactorMateriality.high,
                ),
                FactorDefinition(
                    key="family.divorce_property.registration",
                    label="产权登记",
                    type=FactorType.text,
                    question="房产登记在谁名下？",
                    materiality=FactorMateriality.high,
                ),
                FactorDefinition(
                    key="family.divorce_property.funding_source",
                    label="出资与还贷来源",
                    type=FactorType.text,
                    question="首付款和贷款分别由谁承担，婚后是否共同还贷？",
                    materiality=FactorMateriality.high,
                ),
            ),
        }

    def match_domains(
        self,
        *,
        case_type: str | None,
        legal_issue: str | None,
    ) -> list[str]:
        haystack = " ".join(part for part in (case_type, legal_issue) if part).lower()
        domains: list[str] = []
        if any(term in haystack for term in ("盗窃", "偷窃", "偷东西", "撬门")):
            domains.append("criminal.theft")
        if any(term in haystack for term in ("劳动", "辞退", "解除劳动合同", "赔偿金", "补偿金")):
            domains.append("labor.termination")
        if any(term in haystack for term in ("离婚", "财产分割", "夫妻共同财产", "房产", "房屋")):
            domains.append("family.divorce_property")
        return domains

    def definitions_for(
        self,
        *,
        case_type: str | None,
        legal_issue: str | None,
    ) -> tuple[list[str], list[FactorDefinition]]:
        domains = self.match_domains(case_type=case_type, legal_issue=legal_issue)
        definitions = list(self._core)
        for domain in domains:
            definitions.extend(self._domains.get(domain, ()))
        return domains, definitions
