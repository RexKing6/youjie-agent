"""Restricted ERPNext test-instance adapter for reproducible competition demos.

The adapter deliberately exposes a tiny allowlisted surface. It can read
manufacturing documents and create draft Material Request / Work Order records;
it cannot submit, cancel, delete, invoke arbitrary RPC, or control equipment.
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
from urllib.parse import quote, urlencode, urlparse
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


ALLOWED_READ_DOCTYPES = frozenset({
    "Sales Order",
    "BOM",
    "Bin",
    "Work Order",
    "Job Card",
    "Material Request",
    "Item",
    "Supplier",
    "Warehouse",
})
ALLOWED_CREATE_DOCTYPES = frozenset({"Material Request", "Work Order"})
ALLOWED_RPC_PATHS = frozenset({"/api/method/frappe.auth.get_logged_user"})
RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


class ERPNextAdapterError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.status = status
        self.retryable = retryable


class ERPNextManualReviewRequired(ERPNextAdapterError):
    pass


@dataclass(frozen=True)
class ERPNextConfig:
    base_url: str
    api_key: str
    api_secret: str
    environment: str = "test"
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ERPNext base_url must be an absolute HTTP(S) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote ERPNext instances must use HTTPS")
        if self.environment not in {"sandbox", "test"}:
            raise ValueError("ERPNext adapter refuses non-test environments")
        if not self.api_key or not self.api_secret:
            raise ValueError("ERPNext API key and secret are required")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 60:
            raise ValueError("ERPNext timeout must be between 0 and 60 seconds")

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def public_host(self) -> str:
        parsed = urlparse(self.base_url)
        return parsed.hostname or "unknown"

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "ERPNextConfig | None":
        source = os.environ if values is None else values
        file_values: dict[str, Any] = {}
        credential_file = source.get("DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE", "").strip()
        if credential_file:
            credential_path = Path(credential_file).expanduser()
            if not credential_path.is_file():
                raise ValueError("ERPNext credential file does not exist")
            try:
                loaded = json.loads(credential_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("ERPNext credential file is not valid JSON") from exc
            if not isinstance(loaded, dict):
                raise ValueError("ERPNext credential file must contain a JSON object")
            file_values = loaded

        def setting(env_name: str, file_name: str, default: str = "") -> str:
            direct = source.get(env_name, "").strip()
            if direct:
                return direct
            value = file_values.get(file_name, default)
            return str(value).strip() if value is not None else ""

        base_url = setting("DELIVERY_GUARD_ERPNEXT_BASE_URL", "base_url")
        api_key = setting("DELIVERY_GUARD_ERPNEXT_API_KEY", "api_key")
        api_secret = setting("DELIVERY_GUARD_ERPNEXT_API_SECRET", "api_secret")
        if not any((base_url, api_key, api_secret)):
            return None
        if not all((base_url, api_key, api_secret)):
            raise ValueError("ERPNext configuration is incomplete")
        return cls(
            base_url=base_url,
            api_key=api_key,
            api_secret=api_secret,
            environment=setting("DELIVERY_GUARD_ERPNEXT_ENVIRONMENT", "environment", "test") or "test",
            timeout_seconds=float(setting("DELIVERY_GUARD_ERPNEXT_TIMEOUT_SECONDS", "timeout_seconds", "8")),
        )


class ERPNextMapping(StrictModel):
    schema_version: str = "youjie.erpnext_mapping/v1"
    company: str
    default_warehouse: str
    wip_warehouse: str
    finished_goods_warehouse: str
    scenario_epoch: str
    item_codes: dict[str, str]
    order_to_production_item: dict[str, str]
    order_to_bom: dict[str, str]
    order_quantities: dict[str, int]

    @classmethod
    def from_path(cls, path: str | Path) -> "ERPNextMapping":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))

    def at_hour(self, hour: int) -> str:
        epoch = datetime.fromisoformat(self.scenario_epoch)
        # Frappe DateTime fields are serialized as database-style local time.
        # The scenario epoch retains its explicit timezone internally; only the
        # ERPNext transport boundary drops the offset after applying the hour.
        return (epoch + timedelta(hours=hour)).strftime("%Y-%m-%d %H:%M:%S")

    def date_at_hour(self, hour: int) -> str:
        epoch = datetime.fromisoformat(self.scenario_epoch)
        return (epoch + timedelta(hours=hour)).date().isoformat()


class ERPNextCreatedRecord(StrictModel):
    doctype: str
    name: str
    creation: str | None = None
    modified: str | None = None
    docstatus: int = 0
    status: str | None = None
    evidence_hash: str


class ERPNextExecutionResult(StrictModel):
    command_id: str
    idempotency_key: str
    business_status: BusinessStatus
    duplicate: bool = False
    environment: str = "test"
    public_host: str
    records: list[ERPNextCreatedRecord] = Field(default_factory=list)
    deferred_actions: list[dict[str, Any]] = Field(default_factory=list)
    disclosure: str = "REAL ERPNEXT TEST INSTANCE · DRAFT ONLY · NO NATIVE APPROVAL OR DEVICE CONTROL"


class ERPNextHttpClient:
    def __init__(self, config: ERPNextConfig) -> None:
        self.config = config

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        if not path.startswith("/api/resource/") and path not in ALLOWED_RPC_PATHS:
            raise ERPNextAdapterError("PATH_NOT_ALLOWED", "ERPNext path is outside the allowlist")
        url = self.config.normalized_base_url + path
        if query:
            url += "?" + urlencode(query)
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"token {self.config.api_key}:{self.config.api_secret}",
                "User-Agent": "youjie-erpnext-test-adapter/1.0",
            },
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")[:1000]
            raise ERPNextAdapterError(
                "ERPNEXT_HTTP_ERROR",
                f"ERPNext returned HTTP {exc.code}; response={raw}",
                status=exc.code,
                retryable=exc.code in RETRYABLE_HTTP_STATUSES,
            ) from None
        except (URLError, TimeoutError) as exc:
            raise ERPNextAdapterError(
                "ERPNEXT_UNREACHABLE",
                f"ERPNext request failed: {type(exc).__name__}",
                retryable=True,
            ) from None
        except json.JSONDecodeError:
            raise ERPNextAdapterError("ERPNEXT_INVALID_JSON", "ERPNext returned invalid JSON") from None

    @staticmethod
    def _validate_doctype(doctype: str, *, create: bool = False) -> None:
        allowlist = ALLOWED_CREATE_DOCTYPES if create else ALLOWED_READ_DOCTYPES
        if doctype not in allowlist:
            raise ERPNextAdapterError("DOCTYPE_NOT_ALLOWED", f"doctype {doctype!r} is not allowed")

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/api/method/frappe.auth.get_logged_user")
        user = payload.get("message")
        if not isinstance(user, str) or not user:
            raise ERPNextAdapterError("ERPNEXT_HEALTH_INVALID", "logged-user response is missing")
        return {
            "status": "connected",
            "environment": self.config.environment,
            "public_host": self.config.public_host,
            "authenticated_user": user,
            "credentials_exposed": False,
        }

    def list_documents(
        self,
        doctype: str,
        *,
        fields: list[str] | None = None,
        filters: list[list[Any]] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._validate_doctype(doctype)
        if limit < 1 or limit > 500:
            raise ValueError("ERPNext list limit must be between 1 and 500")
        query = {
            "fields": json.dumps(fields or ["name", "modified", "docstatus"], ensure_ascii=False),
            "limit_page_length": str(limit),
        }
        if filters:
            query["filters"] = json.dumps(filters, ensure_ascii=False)
        payload = self._request("GET", f"/api/resource/{quote(doctype, safe='')}", query=query)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise ERPNextAdapterError("ERPNEXT_LIST_INVALID", f"{doctype} response has no data list")
        return [row for row in rows if isinstance(row, dict)]

    def get_document(self, doctype: str, name: str) -> dict[str, Any]:
        self._validate_doctype(doctype)
        if not name or len(name) > 200:
            raise ValueError("invalid ERPNext document name")
        payload = self._request(
            "GET",
            f"/api/resource/{quote(doctype, safe='')}/{quote(name, safe='')}",
        )
        document = payload.get("data")
        if not isinstance(document, dict):
            raise ERPNextAdapterError("ERPNEXT_DOCUMENT_INVALID", f"{doctype}/{name} has no data object")
        return document

    def create_draft(self, doctype: str, document: dict[str, Any]) -> ERPNextCreatedRecord:
        self._validate_doctype(doctype, create=True)
        if document.get("doctype") not in {None, doctype}:
            raise ERPNextAdapterError("DOCTYPE_MISMATCH", "payload doctype does not match endpoint")
        if int(document.get("docstatus", 0)) != 0:
            raise ERPNextAdapterError("DRAFT_ONLY", "ERPNext adapter may create drafts only")
        safe_document = {**document, "doctype": doctype, "docstatus": 0}
        payload = self._request(
            "POST",
            f"/api/resource/{quote(doctype, safe='')}",
            payload=safe_document,
        )
        created = payload.get("data")
        if not isinstance(created, dict) or not isinstance(created.get("name"), str):
            raise ERPNextAdapterError("ERPNEXT_CREATE_INVALID", f"{doctype} create response has no document name")
        verified = self.get_document(doctype, created["name"])
        if int(verified.get("docstatus", -1)) != 0:
            raise ERPNextAdapterError("DRAFT_VERIFICATION_FAILED", f"{doctype}/{created['name']} is not a draft")
        return ERPNextCreatedRecord(
            doctype=doctype,
            name=created["name"],
            creation=verified.get("creation"),
            modified=verified.get("modified"),
            docstatus=0,
            status=verified.get("status"),
            evidence_hash=stable_hash(verified),
        )


class ERPNextExecutionLedger:
    """Fail-closed idempotency ledger for real external draft creation."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS erpnext_executions (
                idempotency_key TEXT PRIMARY KEY,
                command_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def begin(self, command: CanonicalCommand) -> ERPNextExecutionResult | None:
        row = self.connection.execute(
            "SELECT * FROM erpnext_executions WHERE idempotency_key = ?",
            (command.idempotency_key,),
        ).fetchone()
        if row:
            if row["payload_hash"] != command.payload_hash:
                raise IdempotencyConflict("same ERPNext idempotency_key with different payload")
            if row["status"] == BusinessStatus.APPLIED.value and row["result_json"]:
                result = ERPNextExecutionResult.model_validate_json(row["result_json"])
                return result.model_copy(update={"duplicate": True})
            raise ERPNextManualReviewRequired(
                "ERPNext_RETRY_BLOCKED",
                f"previous execution is {row['status']}; inspect external records before retry",
            )
        with self.connection:
            self.connection.execute(
                "INSERT INTO erpnext_executions VALUES (?, ?, ?, ?, NULL)",
                (
                    command.idempotency_key,
                    command.command_id,
                    command.payload_hash,
                    BusinessStatus.PENDING.value,
                ),
            )
        return None

    def finish(self, result: ERPNextExecutionResult) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE erpnext_executions SET status = ?, result_json = ? WHERE idempotency_key = ?",
                (
                    result.business_status.value,
                    result.model_dump_json(),
                    result.idempotency_key,
                ),
            )

    def mark_manual_review(self, command: CanonicalCommand, records: list[ERPNextCreatedRecord]) -> None:
        partial = ERPNextExecutionResult(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            business_status=BusinessStatus.MANUAL_REVIEW,
            public_host="redacted",
            records=records,
        )
        with self.connection:
            self.connection.execute(
                "UPDATE erpnext_executions SET status = ?, result_json = ? WHERE idempotency_key = ?",
                (
                    BusinessStatus.MANUAL_REVIEW.value,
                    partial.model_dump_json(),
                    command.idempotency_key,
                ),
            )


class ERPNextAdapter:
    def __init__(
        self,
        client: ERPNextHttpClient,
        *,
        ledger: ERPNextExecutionLedger | None = None,
    ) -> None:
        self.client = client
        self.ledger = ledger or ERPNextExecutionLedger()

    def execute(self, command: CanonicalCommand) -> ERPNextExecutionResult:
        if command.profile != IntegrationProfile.ERPNEXT:
            raise ERPNextAdapterError("PROFILE_MISMATCH", "command is not an ERPNext profile")
        if command.target_system != TargetSystem.ERPNEXT:
            raise ERPNextAdapterError("TARGET_MISMATCH", "command does not target ERPNext")
        if command.environment != self.client.config.environment:
            raise ERPNextAdapterError("ENVIRONMENT_MISMATCH", "command and ERPNext environment differ")
        duplicate = self.ledger.begin(command)
        if duplicate:
            return duplicate

        documents = command.payload.get("documents")
        if not isinstance(documents, list) or not documents:
            raise ERPNextAdapterError("NO_DOCUMENTS", "ERPNext command contains no draft documents")
        created: list[ERPNextCreatedRecord] = []
        try:
            for document in documents:
                if not isinstance(document, dict):
                    raise ERPNextAdapterError("INVALID_DOCUMENT", "ERPNext document must be an object")
                doctype = document.get("doctype")
                if not isinstance(doctype, str):
                    raise ERPNextAdapterError("MISSING_DOCTYPE", "ERPNext document has no doctype")
                created.append(self.client.create_draft(doctype, document))
        except Exception:
            self.ledger.mark_manual_review(command, created)
            raise

        result = ERPNextExecutionResult(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            business_status=BusinessStatus.APPLIED,
            environment=self.client.config.environment,
            public_host=self.client.config.public_host,
            records=created,
            deferred_actions=command.payload.get("deferred_actions", []),
        )
        self.ledger.finish(result)
        return result

    def execution_snapshot(
        self,
        watched_records: Mapping[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        entities: dict[str, list[dict[str, Any]]] = {}
        field_map = {
            "Work Order": [
                "name", "modified", "docstatus", "status", "qty", "produced_qty",
                "planned_start_date", "planned_end_date", "actual_start_date", "actual_end_date",
            ],
            "Job Card": [
                "name", "modified", "docstatus", "status", "for_quantity",
                "total_completed_qty", "total_time_in_mins", "actual_start_date", "actual_end_date",
            ],
            "Material Request": [
                "name", "modified", "docstatus", "status", "transaction_date",
                "schedule_date", "per_ordered",
            ],
        }
        if watched_records is None:
            for doctype, fields in field_map.items():
                rows = self.client.list_documents(
                    doctype,
                    fields=fields,
                    limit=100,
                )
                entities[doctype] = rows
        else:
            work_order_names = sorted(set(watched_records.get("Work Order", [])))
            for doctype in ("Work Order", "Material Request"):
                projected: list[dict[str, Any]] = []
                for name in sorted(set(watched_records.get(doctype, []))):
                    document = self.client.get_document(doctype, name)
                    projected.append({field: document.get(field) for field in field_map[doctype]})
                entities[doctype] = projected

            job_card_fields = [*field_map["Job Card"], "work_order"]
            job_cards: list[dict[str, Any]] = []
            if work_order_names:
                candidates = self.client.list_documents(
                    "Job Card",
                    fields=job_card_fields,
                    filters=[["work_order", "in", work_order_names]],
                    limit=100,
                )
                watched_work_orders = set(work_order_names)
                job_cards = [
                    row for row in candidates
                    if row.get("work_order") in watched_work_orders
                ]
            entities["Job Card"] = job_cards
        digest = stable_hash(entities)
        return {
            "schema_version": "youjie.erpnext_snapshot/v1",
            "source_system": "ERPNext",
            "environment": self.client.config.environment,
            "public_host": self.client.config.public_host,
            "source_revision": f"erpnext:{digest[:20]}",
            "content_hash": digest,
            "entities": entities,
            "watched_records": watched_records,
        }


def compare_execution_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changed = before.get("content_hash") != after.get("content_hash")
    changed_entities: list[str] = []
    if changed:
        for doctype, prefix in (
            ("Work Order", "work_order"),
            ("Job Card", "job_card"),
            ("Material Request", "material_request"),
        ):
            old_rows = {row.get("name"): row for row in before.get("entities", {}).get(doctype, [])}
            new_rows = {row.get("name"): row for row in after.get("entities", {}).get(doctype, [])}
            for name in sorted(set(old_rows) | set(new_rows)):
                if old_rows.get(name) != new_rows.get(name):
                    changed_entities.append(f"{prefix}:{name}")
    return {
        "changed": changed,
        "source_revision_before": before.get("source_revision"),
        "source_revision_after": after.get("source_revision"),
        "changed_entities": changed_entities,
        "invalidates_approval": changed,
    }


def _approved_work_orders(graph_result: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if graph_result.get("status") != "completed":
        raise ValueError("only a completed, human-approved graph result may create ERPNext commands")
    workflow = graph_result.get("workflow") or {}
    approval = workflow.get("approval") or {}
    if approval.get("decision") != "approve" or approval.get("valid") is not True:
        raise ValueError("a valid human approval is required")
    work_orders = graph_result.get("work_orders") or []
    if not work_orders:
        raise ValueError("no draft work orders available")
    return approval, work_orders


def _canonical_erpnext_command(
    *,
    command_type: str,
    graph_result: dict[str, Any],
    approval: dict[str, Any],
    expected_source_revision: str,
    payload: dict[str, Any],
    created_at: str,
) -> CanonicalCommand:
    workflow = graph_result["workflow"]
    scenario_hash = workflow["scenario_hash"]
    identity = stable_hash({
        "profile": IntegrationProfile.ERPNEXT.value,
        "command_type": command_type,
        "scenario_hash": scenario_hash,
        "plan_hash": approval["plan_hash"],
        "approval_id": approval["approval_id"],
        "payload": payload,
    })
    correlation_id = f"cor_{stable_hash({'scenario': scenario_hash, 'approval': approval['approval_id']})[:16]}"
    return CanonicalCommand(
        command_id=f"cmd_{identity[:16]}",
        correlation_id=correlation_id,
        causation_id=approval["plan_id"],
        idempotency_key=f"sha256:{identity}",
        profile=IntegrationProfile.ERPNEXT,
        target_system=TargetSystem.ERPNEXT,
        command_type=command_type,
        environment="test",
        scenario_hash=scenario_hash,
        plan_hash=approval["plan_hash"],
        approval_id=approval["approval_id"],
        expected_source_revision=expected_source_revision,
        created_at=created_at,
        payload=payload,
    )


def build_erpnext_commands(
    graph_result: dict[str, Any],
    mapping: ERPNextMapping,
    *,
    expected_source_revision: str,
    created_at: str = "2026-08-30T12:00:00+08:00",
) -> list[CanonicalCommand]:
    approval, work_orders = _approved_work_orders(graph_result)
    selected_plan = next(
        (
            plan for plan in graph_result.get("plans", [])
            if plan.get("plan_id") == approval.get("plan_id")
        ),
        None,
    )
    referenced_commitments = [
        {
            "source_id": purchase["source_id"],
            "supplier_id": purchase["supplier_id"],
            "item_id": purchase["item_id"],
            "quantity": purchase["quantity"],
            "expected_arrival_hour": purchase["arrival_hour"],
            "committed": True,
            "reason": "existing committed supply; referenced only, no new ERP document",
        }
        for purchase in (selected_plan or {}).get("purchases", [])
        if purchase.get("committed") is True
    ]
    committed_source_ids = {item["source_id"] for item in referenced_commitments}
    purchase_documents: list[dict[str, Any]] = []
    schedule_documents: list[dict[str, Any]] = []
    deferred_actions: list[dict[str, Any]] = []

    for draft in work_orders:
        payload = draft["payload"]
        if draft["work_order_type"] == "supplier_purchase_request":
            if payload.get("source_id") in committed_source_ids:
                continue
            item_code = mapping.item_codes[payload["item_id"]]
            purchase_documents.append({
                "doctype": "Material Request",
                "docstatus": 0,
                "material_request_type": "Purchase",
                "company": mapping.company,
                "transaction_date": mapping.date_at_hour(0),
                "schedule_date": mapping.date_at_hour(payload["expected_arrival_hour"]),
                "set_warehouse": mapping.default_warehouse,
                "items": [{
                    "item_code": item_code,
                    "qty": payload["quantity"],
                    "schedule_date": mapping.date_at_hour(payload["expected_arrival_hour"]),
                    "warehouse": mapping.default_warehouse,
                }],
                "remarks": (
                    f"Youjie {draft['work_order_id']} · approval {draft['approval_id']} · "
                    f"source {payload['source_id']} · draft only"
                ),
            })
        elif draft["work_order_type"] == "schedule_change_order":
            order_id = payload["order_id"]
            tasks = payload.get("tasks") or []
            if not tasks:
                continue
            start_hour = min(task["start_hour"] for task in tasks)
            end_hour = max(task["end_hour"] for task in tasks)
            schedule_documents.append({
                "doctype": "Work Order",
                "docstatus": 0,
                "company": mapping.company,
                "production_item": mapping.order_to_production_item[order_id],
                "bom_no": mapping.order_to_bom[order_id],
                "qty": mapping.order_quantities[order_id],
                "wip_warehouse": mapping.wip_warehouse,
                "fg_warehouse": mapping.finished_goods_warehouse,
                "planned_start_date": mapping.at_hour(start_hour),
                "planned_end_date": mapping.at_hour(end_hour),
                "use_multi_level_bom": 1,
            })
        elif draft["work_order_type"] == "customer_communication_task":
            deferred_actions.append({
                "type": "human_customer_communication",
                "source_work_order_id": draft["work_order_id"],
                "reason": "ERPNext adapter does not mutate Sales Orders or send messages",
            })

    commands: list[CanonicalCommand] = []
    if purchase_documents:
        commands.append(_canonical_erpnext_command(
            command_type="ERPNEXT_CREATE_MATERIAL_REQUEST_DRAFTS",
            graph_result=graph_result,
            approval=approval,
            expected_source_revision=expected_source_revision,
            payload={
                "documents": purchase_documents,
                "referenced_commitments": referenced_commitments,
                "deferred_actions": deferred_actions,
            },
            created_at=created_at,
        ))
    if schedule_documents:
        commands.append(_canonical_erpnext_command(
            command_type="ERPNEXT_CREATE_WORK_ORDER_DRAFTS",
            graph_result=graph_result,
            approval=approval,
            expected_source_revision=expected_source_revision,
            payload={
                "documents": schedule_documents,
                "referenced_commitments": referenced_commitments if not purchase_documents else [],
                "deferred_actions": deferred_actions,
            },
            created_at=created_at,
        ))
    if not commands:
        raise ValueError("no supported ERPNext draft commands could be built")
    return commands
