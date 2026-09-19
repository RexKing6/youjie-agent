"""Restricted OpenMES test-instance adapter for the competition demo.

Only OpenMES' official ERP integration surface is used: import approved work
orders, then read production and quality state back. Machine, line, OPC UA,
Modbus, MQTT, and generic authenticated application endpoints are deliberately
outside this adapter's allowlist.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import Field

from delivery_guard.hashing import stable_hash
from delivery_guard.integration.contracts import (
    BusinessStatus,
    CanonicalCommand,
    IntegrationProfile,
    TargetSystem,
)
from delivery_guard.integration.ledger import IdempotencyConflict
from delivery_guard.models import StrictModel


OPENMES_UPSTREAM_COMMIT = "f0ccdd1c7a57804212ed337d340aebfeebacc372"
OPENMES_STATUSES = (
    "PENDING",
    "ACCEPTED",
    "IN_PROGRESS",
    "BLOCKED",
    "PAUSED",
    "CHANGE_HOLD",
    "DONE",
    "REJECTED",
    "CANCELLED",
)
RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class OpenMESAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.status = status
        self.retryable = retryable


class OpenMESManualReviewRequired(OpenMESAdapterError):
    pass


@dataclass(frozen=True)
class OpenMESConfig:
    base_url: str
    api_key: str
    environment: str = "test"
    timeout_seconds: float = 8.0
    upstream_commit: str = OPENMES_UPSTREAM_COMMIT

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenMES base_url must be an absolute HTTP(S) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote OpenMES instances must use HTTPS")
        if self.environment not in {"sandbox", "test"}:
            raise ValueError("OpenMES adapter refuses non-test environments")
        if not self.api_key:
            raise ValueError("OpenMES API key is required")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("OpenMES timeout must be between 0 and 60 seconds")
        if len(self.upstream_commit) != 40:
            raise ValueError("OpenMES upstream commit must be a full git SHA")

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def public_host(self) -> str:
        parsed = urlparse(self.base_url)
        return parsed.netloc or "unknown"

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "OpenMESConfig | None":
        source = os.environ if values is None else values
        file_values: dict[str, Any] = {}
        credential_file = source.get("DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE", "").strip()
        if credential_file:
            credential_path = Path(credential_file).expanduser()
            if not credential_path.is_file():
                raise ValueError("OpenMES credential file does not exist")
            try:
                loaded = json.loads(credential_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("OpenMES credential file is not valid JSON") from exc
            if not isinstance(loaded, dict):
                raise ValueError("OpenMES credential file must contain a JSON object")
            file_values = loaded

        def setting(env_name: str, file_name: str, default: str = "") -> str:
            direct = source.get(env_name, "").strip()
            if direct:
                return direct
            value = file_values.get(file_name, default)
            return str(value).strip() if value is not None else ""

        base_url = setting("DELIVERY_GUARD_OPENMES_BASE_URL", "base_url")
        api_key = setting("DELIVERY_GUARD_OPENMES_API_KEY", "api_key")
        if not any((base_url, api_key)):
            return None
        if not all((base_url, api_key)):
            raise ValueError("OpenMES configuration is incomplete")
        return cls(
            base_url=base_url,
            api_key=api_key,
            environment=setting("DELIVERY_GUARD_OPENMES_ENVIRONMENT", "environment", "test") or "test",
            timeout_seconds=float(setting("DELIVERY_GUARD_OPENMES_TIMEOUT_SECONDS", "timeout_seconds", "8")),
            upstream_commit=setting(
                "DELIVERY_GUARD_OPENMES_UPSTREAM_COMMIT",
                "upstream_commit",
                OPENMES_UPSTREAM_COMMIT,
            ),
        )


class OpenMESMapping(StrictModel):
    schema_version: str = "youjie.openmes_mapping/v1"
    line_code: str
    scenario_epoch: str
    order_to_product_type: dict[str, str]
    order_quantities: dict[str, int]
    order_priorities: dict[str, int]

    @classmethod
    def from_path(cls, path: str | Path) -> "OpenMESMapping":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def at_hour(self, hour: int) -> str:
        return (datetime.fromisoformat(self.scenario_epoch) + timedelta(hours=hour)).isoformat()


class OpenMESWorkOrderRecord(StrictModel):
    order_no: str
    status: str
    planned_qty: float
    produced_qty: float
    line_code: str | None = None
    product_type_code: str | None = None
    completed_at: str | None = None
    updated_at: str | None = None
    evidence_hash: str


class OpenMESExecutionResult(StrictModel):
    command_id: str
    idempotency_key: str
    business_status: BusinessStatus
    duplicate: bool = False
    environment: str = "test"
    public_host: str
    upstream_commit: str = OPENMES_UPSTREAM_COMMIT
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    records: list[OpenMESWorkOrderRecord] = Field(default_factory=list)
    disclosure: str = "REAL OPENMES TEST INSTANCE · WORK-ORDER IMPORT/READ ONLY · NO DEVICE CONTROL"


class OpenMESHttpClient:
    def __init__(self, config: OpenMESConfig) -> None:
        self.config = config

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        allowed_exact = {
            "/api/health",
            "/api/v1/erp/work-orders/import",
            "/api/v1/erp/production/completions",
            "/api/v1/erp/quality/issues",
        }
        if path not in allowed_exact:
            raise OpenMESAdapterError("PATH_NOT_ALLOWED", "OpenMES path is outside the allowlist")
        if method not in {"GET", "POST"}:
            raise OpenMESAdapterError("METHOD_NOT_ALLOWED", "OpenMES adapter only permits GET and POST")
        if method == "POST" and path != "/api/v1/erp/work-orders/import":
            raise OpenMESAdapterError("WRITE_NOT_ALLOWED", "only work-order import is writable")
        url = self.config.normalized_base_url + path
        if query:
            url += "?" + urlencode(query)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "youjie-openmes-test-adapter/1.0",
        }
        if authenticated:
            headers["X-Api-Key"] = self.config.api_key
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")[:1000]
            raise OpenMESAdapterError(
                "OPENMES_HTTP_ERROR",
                f"OpenMES returned HTTP {exc.code}; response={raw}",
                status=exc.code,
                retryable=exc.code in RETRYABLE_HTTP_STATUSES,
            ) from None
        except (URLError, TimeoutError) as exc:
            raise OpenMESAdapterError(
                "OPENMES_UNREACHABLE",
                f"OpenMES request failed: {type(exc).__name__}",
                retryable=True,
            ) from None
        except json.JSONDecodeError:
            raise OpenMESAdapterError("OPENMES_INVALID_JSON", "OpenMES returned invalid JSON") from None

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/health", authenticated=False)
        if payload.get("status") != "ok":
            raise OpenMESAdapterError("OPENMES_HEALTH_INVALID", "OpenMES health response is not ok")
        return {
            "status": "connected",
            "environment": self.config.environment,
            "public_host": self.config.public_host,
            "upstream_commit": self.config.upstream_commit,
            "credentials_exposed": False,
        }

    def import_work_orders(self, orders: list[dict[str, Any]]) -> dict[str, Any]:
        if not orders:
            raise ValueError("OpenMES work-order import requires at least one order")
        payload = self._request(
            "POST",
            "/api/v1/erp/work-orders/import",
            payload={"strategy": "update_or_create", "orders": orders},
        )
        result = payload.get("data")
        if not isinstance(result, dict):
            raise OpenMESAdapterError("OPENMES_IMPORT_INVALID", "OpenMES import response has no data object")
        errors = result.get("errors") or []
        if errors:
            raise OpenMESAdapterError("OPENMES_IMPORT_PARTIAL", f"OpenMES rejected rows: {errors}")
        return result

    def work_order_snapshot(self, order_nos: list[str]) -> dict[str, Any]:
        wanted = set(order_nos)
        found: dict[str, dict[str, Any]] = {}
        for status in OPENMES_STATUSES:
            cursor, seen_cursors = None, set()
            for _ in range(100):
                query = {"status": status, "per_page": "100"}
                if cursor:
                    query["cursor"] = cursor
                payload = self._request("GET", "/api/v1/erp/production/completions", query=query)
                rows = payload.get("data")
                if not isinstance(rows, list):
                    raise OpenMESAdapterError("OPENMES_EXPORT_INVALID", "OpenMES production response has no data list")
                for row in rows:
                    if isinstance(row, dict) and row.get("order_no") in wanted:
                        name = str(row["order_no"])
                        if name in found and found[name] != row:
                            raise OpenMESAdapterError("OPENMES_SNAPSHOT_CONFLICT", "work order changed during paginated read")
                        found[name] = row
                meta = payload.get("meta") or {}
                if len(found) == len(wanted) or not meta.get("has_more"):
                    break
                cursor = meta.get("next_cursor")
                if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                    raise OpenMESAdapterError("OPENMES_CURSOR_INVALID", "pagination cursor missing or repeated")
                seen_cursors.add(cursor)
            else:
                raise OpenMESAdapterError("OPENMES_PAGE_LIMIT", "bounded export incomplete; do not infer missing records")
            if len(found) == len(wanted):
                break
        records = []
        for order_no in sorted(wanted):
            row = found.get(order_no)
            if row is None:
                continue
            records.append({
                "order_no": order_no,
                "status": str(row.get("status")),
                "planned_qty": float(row.get("planned_qty") or 0),
                "produced_qty": float(row.get("produced_qty") or 0),
                "line_code": row.get("line_code"),
                "product_type_code": row.get("product_type_code"),
                "completed_at": row.get("completed_at"),
                "updated_at": row.get("updated_at"),
                "evidence_hash": stable_hash(row),
            })
        digest = stable_hash(records)
        return {
            "schema_version": "youjie.openmes_snapshot/v1",
            "source_system": "OpenMES",
            "environment": self.config.environment,
            "public_host": self.config.public_host,
            "upstream_commit": self.config.upstream_commit,
            "source_revision": f"openmes:{digest[:20]}",
            "content_hash": digest,
            "records": records,
            "watched_order_nos": sorted(wanted),
            "missing_order_nos": sorted(wanted - set(found)),
        }


class OpenMESExecutionLedger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS openmes_executions (
                idempotency_key TEXT PRIMARY KEY,
                command_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT
            )
            """
        )
        self.connection.commit()

    def begin(self, command: CanonicalCommand) -> OpenMESExecutionResult | None:
        row = self.connection.execute(
            "SELECT * FROM openmes_executions WHERE idempotency_key = ?",
            (command.idempotency_key,),
        ).fetchone()
        if row:
            if row["payload_hash"] != command.payload_hash:
                raise IdempotencyConflict("same OpenMES idempotency_key with different payload")
            if row["status"] == BusinessStatus.APPLIED.value and row["result_json"]:
                result = OpenMESExecutionResult.model_validate_json(row["result_json"])
                return result.model_copy(update={"duplicate": True})
            raise OpenMESManualReviewRequired(
                "OPENMES_RETRY_BLOCKED",
                f"previous execution is {row['status']}; inspect OpenMES before retry",
            )
        with self.connection:
            self.connection.execute(
                "INSERT INTO openmes_executions VALUES (?, ?, ?, ?, NULL)",
                (command.idempotency_key, command.command_id, command.payload_hash, BusinessStatus.PENDING.value),
            )
        return None

    def finish(self, result: OpenMESExecutionResult) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE openmes_executions SET status = ?, result_json = ? WHERE idempotency_key = ?",
                (result.business_status.value, result.model_dump_json(), result.idempotency_key),
            )


class OpenMESAdapter:
    def __init__(self, client: OpenMESHttpClient, *, ledger: OpenMESExecutionLedger | None = None) -> None:
        self.client = client
        self.ledger = ledger or OpenMESExecutionLedger()

    def execute(self, command: CanonicalCommand) -> OpenMESExecutionResult:
        if command.profile != IntegrationProfile.OPENMES:
            raise OpenMESAdapterError("PROFILE_MISMATCH", "command is not an OpenMES profile")
        if command.target_system != TargetSystem.OPENMES:
            raise OpenMESAdapterError("TARGET_MISMATCH", "command does not target OpenMES")
        if command.environment != self.client.config.environment:
            raise OpenMESAdapterError("ENVIRONMENT_MISMATCH", "command and OpenMES environment differ")
        duplicate = self.ledger.begin(command)
        if duplicate:
            return duplicate
        orders = command.payload.get("orders")
        if not isinstance(orders, list) or not orders:
            raise OpenMESAdapterError("NO_ORDERS", "OpenMES command contains no work orders")
        imported = self.client.import_work_orders(orders)
        snapshot = self.client.work_order_snapshot([str(item["order_no"]) for item in orders])
        if snapshot["missing_order_nos"]:
            raise OpenMESManualReviewRequired(
                "OPENMES_READBACK_MISSING",
                f"imported work orders missing on readback: {snapshot['missing_order_nos']}",
            )
        expected = {str(o["order_no"]):o for o in orders}
        for row in snapshot["records"]:
            wanted = expected[row["order_no"]]
            if (float(row["planned_qty"]) != float(wanted["planned_qty"])
                    or row.get("line_code") != wanted.get("line_code")
                    or row.get("product_type_code") != wanted.get("product_type_code")):
                raise OpenMESManualReviewRequired("OPENMES_READBACK_MISMATCH", "imported work order differs from approved payload")
        result = OpenMESExecutionResult(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            business_status=BusinessStatus.APPLIED,
            environment=self.client.config.environment,
            public_host=self.client.config.public_host,
            upstream_commit=self.client.config.upstream_commit,
            imported=int(imported.get("imported", 0)),
            updated=int(imported.get("updated", 0)),
            skipped=int(imported.get("skipped", 0)),
            records=[OpenMESWorkOrderRecord.model_validate(row) for row in snapshot["records"]],
        )
        self.ledger.finish(result)
        return result

    def execution_snapshot(self, order_nos: list[str]) -> dict[str, Any]:
        return self.client.work_order_snapshot(order_nos)


def compare_openmes_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed = before.get("content_hash") != after.get("content_hash")
    old_rows = {row.get("order_no"): row for row in before.get("records", [])}
    new_rows = {row.get("order_no"): row for row in after.get("records", [])}
    changed_entities = [
        f"openmes_work_order:{order_no}"
        for order_no in sorted(set(old_rows) | set(new_rows))
        if old_rows.get(order_no) != new_rows.get(order_no)
    ]
    return {
        "changed": changed,
        "source_revision_before": before.get("source_revision"),
        "source_revision_after": after.get("source_revision"),
        "changed_entities": changed_entities,
        "invalidates_approval": changed,
    }


def build_openmes_command(
    graph_result: dict[str, Any],
    mapping: OpenMESMapping,
    erpnext_links: list[dict[str, Any]],
    *,
    expected_source_revision: str,
    created_at: str = "2026-08-30T15:00:00+08:00",
) -> CanonicalCommand:
    if graph_result.get("status") != "completed":
        raise ValueError("only a completed, human-approved result may create an OpenMES command")
    workflow = graph_result.get("workflow") or {}
    approval = workflow.get("approval") or {}
    if approval.get("decision") != "approve" or approval.get("valid") is not True:
        raise ValueError("a valid human approval is required")
    orders = []
    for link in erpnext_links:
        order_id = str(link["order_id"])
        orders.append({
            "order_no": str(link["erpnext_work_order"]),
            "customer_order_no": order_id,
            "line_code": mapping.line_code,
            "product_type_code": mapping.order_to_product_type[order_id],
            "planned_qty": mapping.order_quantities[order_id],
            "priority": mapping.order_priorities[order_id],
            "due_date": mapping.at_hour(24),
            "description": (
                f"Youjie approved recovery · source ERPNext {link['erpnext_work_order']} · "
                f"scenario {workflow['scenario_hash']} · plan {approval['plan_hash']} · "
                f"approval {approval['approval_id']} · test only"
            ),
        })
    if not orders:
        raise ValueError("no ERPNext work orders are available for OpenMES import")
    payload = {"strategy": "update_or_create", "orders": orders}
    identity = stable_hash({
        "profile": IntegrationProfile.OPENMES.value,
        "scenario_hash": workflow["scenario_hash"],
        "plan_hash": approval["plan_hash"],
        "approval_id": approval["approval_id"],
        "payload": payload,
    })
    return CanonicalCommand(
        command_id=f"cmd_{identity[:16]}",
        correlation_id=f"cor_{stable_hash({'openmes': identity})[:16]}",
        causation_id=approval["plan_id"],
        idempotency_key=f"sha256:{identity}",
        profile=IntegrationProfile.OPENMES,
        target_system=TargetSystem.OPENMES,
        command_type="OPENMES_IMPORT_APPROVED_WORK_ORDERS",
        environment="test",
        scenario_hash=workflow["scenario_hash"],
        plan_hash=approval["plan_hash"],
        approval_id=approval["approval_id"],
        expected_source_revision=expected_source_revision,
        created_at=created_at,
        payload=payload,
    )
