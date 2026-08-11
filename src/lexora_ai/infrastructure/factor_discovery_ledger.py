from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from lexora_ai.domain.factor_discovery import (
    FactorTokenBudgetSnapshot,
    FactorTokenReservation,
)

FACTOR_DISCOVERY_TOKEN_LIMIT = 100_000_000
FACTOR_DISCOVERY_TOKEN_SCOPE = "factor-discovery"


class FactorDiscoveryLedgerError(ValueError):
    pass


class FactorDiscoveryTokenLedger:
    def __init__(
        self,
        path: Path,
        *,
        limit_tokens: int = FACTOR_DISCOVERY_TOKEN_LIMIT,
        scope: str = FACTOR_DISCOVERY_TOKEN_SCOPE,
    ) -> None:
        if limit_tokens <= 0:
            raise FactorDiscoveryLedgerError("token limit must be positive")
        self._path = path
        self._limit_tokens = limit_tokens
        self._scope = scope
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def snapshot(self) -> FactorTokenBudgetSnapshot:
        with self._connect() as connection:
            return self._snapshot(connection)

    def reserve(self, reservation_key: str, estimated_tokens: int) -> FactorTokenReservation:
        key = _validate_reservation(reservation_key, estimated_tokens)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT estimated_tokens, status
                FROM factor_token_reservations
                WHERE scope = ? AND reservation_key = ?
                """,
                (self._scope, key),
            ).fetchone()
            if existing is not None:
                existing_estimate, status = int(existing[0]), str(existing[1])
                if existing_estimate != estimated_tokens:
                    raise FactorDiscoveryLedgerError(
                        "reservation key already exists with a different estimate"
                    )
                if status == "released":
                    connection.execute(
                        """
                        UPDATE factor_token_reservations
                        SET status = 'reserved', updated_at = ?
                        WHERE scope = ? AND reservation_key = ?
                        """,
                        (_now(), self._scope, key),
                    )
                    outcome = "reserved"
                else:
                    outcome = "unchanged"
                budget = self._snapshot(connection)
                if status == "released" and budget.remaining_tokens < 0:
                    raise FactorDiscoveryLedgerError("cumulative token budget is exhausted")
                connection.commit()
                return FactorTokenReservation(
                    reservation_key=key,
                    estimated_tokens=estimated_tokens,
                    status="reserved" if status == "released" else status,
                    outcome=outcome,
                    budget=budget,
                )

            budget = self._snapshot(connection)
            if estimated_tokens > budget.remaining_tokens:
                raise FactorDiscoveryLedgerError("cumulative token budget is exhausted")
            now = _now()
            connection.execute(
                """
                INSERT INTO factor_token_reservations (
                    scope, reservation_key, estimated_tokens, input_tokens,
                    output_tokens, status, created_at, updated_at
                ) VALUES (?, ?, ?, 0, 0, 'reserved', ?, ?)
                """,
                (self._scope, key, estimated_tokens, now, now),
            )
            connection.commit()
            return FactorTokenReservation(
                reservation_key=key,
                estimated_tokens=estimated_tokens,
                status="reserved",
                outcome="reserved",
                budget=self.snapshot(),
            )

    def settle(
        self,
        reservation_key: str,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> FactorTokenReservation:
        key = _validate_reservation(reservation_key, 1)
        if input_tokens < 0 or output_tokens < 0:
            raise FactorDiscoveryLedgerError("actual token counts cannot be negative")
        actual_tokens = input_tokens + output_tokens
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT estimated_tokens, input_tokens, output_tokens, status
                FROM factor_token_reservations
                WHERE scope = ? AND reservation_key = ?
                """,
                (self._scope, key),
            ).fetchone()
            if existing is None:
                raise FactorDiscoveryLedgerError("token reservation does not exist")
            estimated, recorded_input, recorded_output, status = existing
            if status == "settled":
                if (int(recorded_input), int(recorded_output)) != (input_tokens, output_tokens):
                    raise FactorDiscoveryLedgerError(
                        "settled reservation already has different actual token counts"
                    )
                connection.commit()
                return FactorTokenReservation(
                    reservation_key=key,
                    estimated_tokens=int(estimated),
                    status="settled",
                    outcome="unchanged",
                    budget=self.snapshot(),
                )
            if status != "reserved":
                raise FactorDiscoveryLedgerError("released reservation cannot be settled")

            budget = self._snapshot(connection)
            available_after_release = budget.remaining_tokens + int(estimated)
            if actual_tokens > available_after_release:
                raise FactorDiscoveryLedgerError("actual usage exceeds cumulative token budget")
            connection.execute(
                """
                UPDATE factor_token_reservations
                SET input_tokens = ?, output_tokens = ?, status = 'settled', updated_at = ?
                WHERE scope = ? AND reservation_key = ?
                """,
                (input_tokens, output_tokens, _now(), self._scope, key),
            )
            connection.commit()
            return FactorTokenReservation(
                reservation_key=key,
                estimated_tokens=int(estimated),
                status="settled",
                outcome="settled",
                budget=self.snapshot(),
            )

    def release(self, reservation_key: str) -> FactorTokenReservation:
        key = _validate_reservation(reservation_key, 1)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT estimated_tokens, status
                FROM factor_token_reservations
                WHERE scope = ? AND reservation_key = ?
                """,
                (self._scope, key),
            ).fetchone()
            if existing is None:
                raise FactorDiscoveryLedgerError("token reservation does not exist")
            estimated, status = int(existing[0]), str(existing[1])
            if status == "settled":
                raise FactorDiscoveryLedgerError("settled reservation cannot be released")
            outcome = "unchanged"
            if status == "reserved":
                connection.execute(
                    """
                    UPDATE factor_token_reservations
                    SET status = 'released', updated_at = ?
                    WHERE scope = ? AND reservation_key = ?
                    """,
                    (_now(), self._scope, key),
                )
                outcome = "released"
            connection.commit()
            return FactorTokenReservation(
                reservation_key=key,
                estimated_tokens=estimated,
                status="released",
                outcome=outcome,
                budget=self.snapshot(),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_token_scopes (
                    scope TEXT PRIMARY KEY,
                    limit_tokens INTEGER NOT NULL CHECK (limit_tokens > 0),
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_token_reservations (
                    scope TEXT NOT NULL,
                    reservation_key TEXT NOT NULL,
                    estimated_tokens INTEGER NOT NULL CHECK (estimated_tokens > 0),
                    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
                    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
                    status TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'released')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, reservation_key),
                    FOREIGN KEY (scope) REFERENCES factor_token_scopes(scope)
                )
                """
            )
            row = connection.execute(
                "SELECT limit_tokens FROM factor_token_scopes WHERE scope = ?",
                (self._scope,),
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO factor_token_scopes (scope, limit_tokens, created_at) VALUES (?, ?, ?)",
                    (self._scope, self._limit_tokens, _now()),
                )
            elif int(row[0]) != self._limit_tokens:
                raise FactorDiscoveryLedgerError(
                    "existing cumulative token limit differs from configured limit"
                )
            connection.commit()

    def _snapshot(self, connection: sqlite3.Connection) -> FactorTokenBudgetSnapshot:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'settled' THEN input_tokens + output_tokens ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN status = 'reserved' THEN estimated_tokens ELSE 0 END), 0)
            FROM factor_token_reservations
            WHERE scope = ?
            """,
            (self._scope,),
        ).fetchone()
        consumed, reserved = int(row[0]), int(row[1])
        return FactorTokenBudgetSnapshot(
            scope=self._scope,
            limit_tokens=self._limit_tokens,
            consumed_tokens=consumed,
            reserved_tokens=reserved,
            remaining_tokens=self._limit_tokens - consumed - reserved,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _validate_reservation(reservation_key: str, estimated_tokens: int) -> str:
    key = reservation_key.strip()
    if not key:
        raise FactorDiscoveryLedgerError("reservation key cannot be empty")
    if estimated_tokens <= 0:
        raise FactorDiscoveryLedgerError("estimated tokens must be positive")
    return key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
