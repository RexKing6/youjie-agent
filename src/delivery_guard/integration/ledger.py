"""SQLite outbox/inbox ledger for observable, idempotent sandbox integration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from delivery_guard.integration.contracts import BusinessStatus, CanonicalCommand, ExecutionCallback


class IdempotencyConflict(ValueError):
    """The same business idempotency key was reused with a different payload."""


class IntegrationLedger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                correlation_id TEXT NOT NULL,
                target_system TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                business_status TEXT NOT NULL,
                operation_id TEXT,
                last_sequence INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS outbox (
                command_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(command_id) REFERENCES commands(command_id)
            );
            CREATE TABLE IF NOT EXISTS inbox (
                event_id TEXT PRIMARY KEY,
                command_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                ref_id TEXT NOT NULL,
                details_json TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def queue(self, command: CanonicalCommand) -> tuple[bool, str | None, BusinessStatus]:
        raw = json.dumps(command.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        existing = self.connection.execute(
            "SELECT * FROM commands WHERE idempotency_key = ?", (command.idempotency_key,)
        ).fetchone()
        if existing:
            if existing["payload_hash"] != command.payload_hash:
                raise IdempotencyConflict("same idempotency_key with different payload")
            return True, existing["operation_id"], BusinessStatus(existing["business_status"])
        with self.connection:
            self.connection.execute(
                "INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0)",
                (
                    command.command_id,
                    command.idempotency_key,
                    command.correlation_id,
                    command.target_system.value,
                    command.payload_hash,
                    raw,
                    BusinessStatus.PENDING.value,
                ),
            )
            self.connection.execute(
                "INSERT INTO outbox(command_id, status, attempt_count) VALUES (?, 'QUEUED', 0)",
                (command.command_id,),
            )
            self._audit(command.correlation_id, "COMMAND_QUEUED", command.command_id, {
                "target_system": command.target_system.value,
                "payload_hash": command.payload_hash,
                "idempotency_key": command.idempotency_key,
            })
        return False, None, BusinessStatus.PENDING

    def mark_sent(self, command: CanonicalCommand, operation_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE commands SET operation_id = ? WHERE command_id = ?",
                (operation_id, command.command_id),
            )
            self.connection.execute(
                "UPDATE outbox SET status = 'SENT', attempt_count = attempt_count + 1 WHERE command_id = ?",
                (command.command_id,),
            )
            self._audit(command.correlation_id, "TRANSPORT_ACCEPTED", command.command_id, {
                "operation_id": operation_id,
                "business_status": BusinessStatus.PENDING.value,
            })

    def record_callback(self, callback: ExecutionCallback) -> tuple[bool, bool, BusinessStatus]:
        duplicate = self.connection.execute(
            "SELECT payload_hash FROM inbox WHERE event_id = ?", (callback.event_id,)
        ).fetchone()
        if duplicate:
            if duplicate["payload_hash"] != callback.evidence_hash:
                raise IdempotencyConflict("same callback event_id with different payload")
            current = self.command_status(callback.command_id)
            return True, False, current

        row = self.connection.execute(
            "SELECT business_status, last_sequence, correlation_id FROM commands WHERE command_id = ?",
            (callback.command_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"unknown command_id {callback.command_id}")
        stale_sequence = callback.sequence <= row["last_sequence"]
        with self.connection:
            self.connection.execute(
                "INSERT INTO inbox VALUES (?, ?, ?, ?, ?)",
                (
                    callback.event_id,
                    callback.command_id,
                    callback.evidence_hash,
                    callback.sequence,
                    json.dumps(callback.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                ),
            )
            if not stale_sequence:
                self.connection.execute(
                    "UPDATE commands SET business_status = ?, last_sequence = ? WHERE command_id = ?",
                    (callback.business_status.value, callback.sequence, callback.command_id),
                )
            self._audit(row["correlation_id"], "CALLBACK_DUPLICATE_OR_STALE" if stale_sequence else "BUSINESS_CALLBACK", callback.event_id, {
                "command_id": callback.command_id,
                "business_status": callback.business_status.value,
                "sequence": callback.sequence,
                "stale_sequence": stale_sequence,
                "changed_entities": callback.changed_entities,
            })
        return False, stale_sequence, self.command_status(callback.command_id)

    def command_status(self, command_id: str) -> BusinessStatus:
        row = self.connection.execute(
            "SELECT business_status FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"unknown command_id {command_id}")
        return BusinessStatus(row["business_status"])

    def command(self, command_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"unknown command_id {command_id}")
        return dict(row)

    def audit_events(self, correlation_id: str | None = None) -> list[dict[str, Any]]:
        if correlation_id:
            rows = self.connection.execute(
                "SELECT * FROM audit WHERE correlation_id = ? ORDER BY sequence", (correlation_id,)
            ).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM audit ORDER BY sequence").fetchall()
        return [
            {**dict(row), "details": json.loads(row["details_json"])}
            for row in rows
        ]

    def command_rows(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT command_id, correlation_id, target_system, business_status, operation_id, last_sequence FROM commands ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]

    def _audit(self, correlation_id: str, event_type: str, ref_id: str, details: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO audit(correlation_id, event_type, ref_id, details_json) VALUES (?, ?, ?, ?)",
            (correlation_id, event_type, ref_id, json.dumps(details, ensure_ascii=False, sort_keys=True)),
        )
