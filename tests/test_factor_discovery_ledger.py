from pathlib import Path

import pytest

from lexora_ai.infrastructure.factor_discovery_ledger import (
    FactorDiscoveryLedgerError,
    FactorDiscoveryTokenLedger,
)


def test_ledger_is_persistent_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "budget.sqlite3"
    ledger = FactorDiscoveryTokenLedger(path, limit_tokens=10_000)

    first = ledger.reserve("batch-a", 3_000)
    repeated = ledger.reserve("batch-a", 3_000)
    settled = ledger.settle("batch-a", input_tokens=2_100, output_tokens=400)
    settled_again = ledger.settle("batch-a", input_tokens=2_100, output_tokens=400)
    reopened = FactorDiscoveryTokenLedger(path, limit_tokens=10_000).snapshot()

    assert first.outcome == "reserved"
    assert repeated.outcome == "unchanged"
    assert repeated.budget.reserved_tokens == 3_000
    assert settled.budget.consumed_tokens == 2_500
    assert settled.budget.reserved_tokens == 0
    assert settled_again.outcome == "unchanged"
    assert reopened.consumed_tokens == 2_500
    assert reopened.remaining_tokens == 7_500


def test_ledger_releases_unused_reservation_without_consuming_tokens(tmp_path: Path) -> None:
    ledger = FactorDiscoveryTokenLedger(tmp_path / "budget.sqlite3", limit_tokens=10_000)

    ledger.reserve("batch-a", 4_000)
    released = ledger.release("batch-a")
    released_again = ledger.release("batch-a")

    assert released.outcome == "released"
    assert released.budget.consumed_tokens == 0
    assert released.budget.remaining_tokens == 10_000
    assert released_again.outcome == "unchanged"


def test_ledger_rejects_reservations_beyond_cumulative_limit(tmp_path: Path) -> None:
    ledger = FactorDiscoveryTokenLedger(tmp_path / "budget.sqlite3", limit_tokens=10_000)
    ledger.reserve("batch-a", 9_000)

    with pytest.raises(FactorDiscoveryLedgerError, match="exhausted"):
        ledger.reserve("batch-b", 1_001)


def test_ledger_settles_actual_usage_even_when_it_exceeds_estimate(tmp_path: Path) -> None:
    ledger = FactorDiscoveryTokenLedger(tmp_path / "budget.sqlite3", limit_tokens=10_000)
    ledger.reserve("batch-a", 3_000)

    settled = ledger.settle("batch-a", input_tokens=2_800, output_tokens=700)

    assert settled.budget.consumed_tokens == 3_500
    assert settled.budget.reserved_tokens == 0
    assert settled.budget.remaining_tokens == 6_500


def test_ledger_limit_cannot_be_reset_by_reopening_database(tmp_path: Path) -> None:
    path = tmp_path / "budget.sqlite3"
    FactorDiscoveryTokenLedger(path, limit_tokens=10_000)

    with pytest.raises(FactorDiscoveryLedgerError, match="differs"):
        FactorDiscoveryTokenLedger(path, limit_tokens=20_000)
