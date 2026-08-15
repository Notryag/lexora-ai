from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, model_validator


class EmploymentTerminationCompensationInput(BaseModel):
    completed_years: int = Field(
        ge=0,
        le=80,
        description="解除劳动合同时已经完成的整年工作年限。",
    )
    additional_months: int = Field(
        ge=0,
        le=11,
        description="整年之外的剩余工作月数，范围为 0 至 11。",
    )
    monthly_wage: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="劳动合同解除或终止前十二个月的平均月工资。",
    )
    local_average_monthly_wage: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=14,
        decimal_places=2,
        description=(
            "用人单位所在直辖市或设区的市上年度职工月平均工资；未知时留空，"
            "工具会明确提示尚未核验三倍工资封顶规则。"
        ),
    )

    @model_validator(mode="after")
    def reject_zero_service(self) -> EmploymentTerminationCompensationInput:
        if self.completed_years == 0 and self.additional_months == 0:
            raise ValueError("service duration must be greater than zero")
        return self


def calculate_employment_termination_compensation(
    data: EmploymentTerminationCompensationInput,
) -> dict[str, object]:
    """Calculate mainland China Labor Contract Law Article 47 N and 2N amounts."""
    remainder_credit = Decimal("0")
    if 1 <= data.additional_months < 6:
        remainder_credit = Decimal("0.5")
    elif data.additional_months >= 6:
        remainder_credit = Decimal("1")

    compensation_months = Decimal(data.completed_years) + remainder_credit
    wage_basis = data.monthly_wage
    cap_applied: bool | None = None
    if data.local_average_monthly_wage is not None:
        statutory_wage_cap = data.local_average_monthly_wage * Decimal("3")
        cap_applied = data.monthly_wage > statutory_wage_cap
        if cap_applied:
            wage_basis = statutory_wage_cap
            compensation_months = min(compensation_months, Decimal("12"))

    economic_compensation = wage_basis * compensation_months
    unlawful_termination_damages = economic_compensation * Decimal("2")

    def decimal_text(value: Decimal) -> str:
        return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")

    notes = [
        "不足六个月按半个月工资计算，六个月以上不满一年按一个月工资计算。",
        "2N 仅表示违法解除或违法终止时按经济补偿标准二倍计算的金额，不判断本案是否属于违法解除。",
    ]
    if data.local_average_monthly_wage is None:
        notes.append(
            "未提供当地上年度职工月平均工资，结果尚未核验月工资三倍封顶及高工资者十二年封顶规则。"
        )

    return {
        "compensation_months": decimal_text(compensation_months),
        "monthly_wage_basis": decimal_text(wage_basis),
        "economic_compensation_n": decimal_text(economic_compensation),
        "unlawful_termination_damages_2n": decimal_text(
            unlawful_termination_damages
        ),
        "wage_cap_applied": cap_applied,
        "notes": notes,
    }
