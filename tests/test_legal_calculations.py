from decimal import Decimal

import pytest
from pydantic import ValidationError

from lexora_ai.domain.legal_calculations import (
    EmploymentTerminationCompensationInput,
    calculate_employment_termination_compensation,
)


def test_employment_compensation_credits_partial_year_correctly() -> None:
    result = calculate_employment_termination_compensation(
        EmploymentTerminationCompensationInput(
            completed_years=3,
            additional_months=2,
            monthly_wage=Decimal("10000"),
        )
    )

    assert result["compensation_months"] == "3.50"
    assert result["economic_compensation_n"] == "35000.00"
    assert result["unlawful_termination_damages_2n"] == "70000.00"
    assert result["wage_cap_applied"] is None


def test_employment_compensation_applies_high_wage_and_year_caps() -> None:
    result = calculate_employment_termination_compensation(
        EmploymentTerminationCompensationInput(
            completed_years=15,
            additional_months=8,
            monthly_wage=Decimal("50000"),
            local_average_monthly_wage=Decimal("10000"),
        )
    )

    assert result["compensation_months"] == "12.00"
    assert result["monthly_wage_basis"] == "30000.00"
    assert result["economic_compensation_n"] == "360000.00"
    assert result["unlawful_termination_damages_2n"] == "720000.00"
    assert result["wage_cap_applied"] is True


def test_employment_compensation_rejects_zero_service_duration() -> None:
    with pytest.raises(ValidationError, match="service duration must be greater than zero"):
        EmploymentTerminationCompensationInput(
            completed_years=0,
            additional_months=0,
            monthly_wage=Decimal("10000"),
        )
