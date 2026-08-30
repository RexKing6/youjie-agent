"""In-process business sandbox with a real localhost HTTP boundary."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from delivery_guard.hashing import stable_hash
from delivery_guard.integration.contracts import (
    AdapterCapability,
    BusinessStatus,
    CallbackReceipt,
    CanonicalCommand,
    ExecutionCallback,
    IntegrationError,
    IntegrationProfile,
    TransportAck,
    TransportStatus,
)
from delivery_guard.integration.ledger import IdempotencyConflict, IntegrationLedger


DEPENDENCY_PREFIXES = (
    "order:", "bom:", "inventory:", "supplier_commitment:",
    "capacity:", "resource_status:", "production_line:",
)


class ContractSandbox:
    def __init__(
        self,
        *,
        profile: IntegrationProfile,
        snapshots: dict[str, Any],
        ledger: IntegrationLedger | None = None,
    ) -> None:
        self.profile = profile
        self.snapshots = snapshots
        self.ledger = ledger or IntegrationLedger()
        self.capability = AdapterCapability(profile=profile)

    def submit(self, command: CanonicalCommand) -> TransportAck:
        if command.profile != self.profile:
            raise ValueError(f"profile mismatch: {command.profile} != {self.profile}")
        duplicate, existing_operation, status = self.ledger.queue(command)
        operation_id = existing_operation or f"extop_{stable_hash({'key': command.idempotency_key})[:16]}"
        if not duplicate:
            self.ledger.mark_sent(command, operation_id)
        return TransportAck(
            ack_id=f"ack_{stable_hash({'command_id': command.command_id})[:16]}",
            command_id=command.command_id,
            correlation_id=command.correlation_id,
            idempotency_key=command.idempotency_key,
            operation_id=operation_id,
            transport_status=TransportStatus.ACCEPTED,
            business_status=status,
            duplicate=duplicate,
            received_at=command.created_at,
        )

    def receive_callback(self, callback: ExecutionCallback) -> CallbackReceipt:
        command = self.ledger.command(callback.command_id)
        if command["operation_id"] != callback.operation_id:
            raise ValueError("callback operation_id does not match command")
        duplicate, stale_sequence, current_status = self.ledger.record_callback(callback)
        plan_stale = any(
            entity.startswith(DEPENDENCY_PREFIXES)
            for entity in callback.changed_entities
        )
        return CallbackReceipt(
            event_id=callback.event_id,
            command_id=callback.command_id,
            operation_id=callback.operation_id,
            accepted=True,
            duplicate=duplicate,
            stale_sequence=stale_sequence,
            current_business_status=current_status,
            plan_stale=plan_stale,
        )

    def operation(self, operation_id: str) -> dict[str, Any]:
        rows = [row for row in self.ledger.command_rows() if row["operation_id"] == operation_id]
        if not rows:
            raise ValueError(f"unknown operation_id {operation_id}")
        return rows[0]

    def audit(self, correlation_id: str) -> list[dict[str, Any]]:
        return self.ledger.audit_events(correlation_id)


class SandboxHttpService:
    """Threaded localhost service used by the UI and integration tests."""

    def __init__(self, sandbox: ContractSandbox, host: str = "127.0.0.1", port: int = 0) -> None:
        self.sandbox = sandbox
        handler = self._handler_type()
        self.server = ThreadingHTTPServer((host, port), handler)
        self.server.sandbox_service = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> "SandboxHttpService":
        if not self.thread.is_alive():
            self.thread.start()
        return self

    def close(self) -> None:
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()

    @staticmethod
    def _handler_type() -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            server_version = "YoujieContractSandbox/1.0"

            @property
            def service(self) -> "SandboxHttpService":
                return self.server.sandbox_service  # type: ignore[attr-defined]

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _send(self, status: int, payload: Any) -> None:
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def do_GET(self) -> None:  # noqa: N802
                try:
                    if self.path == "/health":
                        self._send(200, {
                            "status": "ok",
                            "capability": self.service.sandbox.capability.model_dump(mode="json"),
                        })
                    elif self.path.startswith("/sandbox/v1/erp/snapshots/"):
                        self._send(200, self.service.sandbox.snapshots["erp"])
                    elif self.path.startswith("/sandbox/v1/mes/snapshots/"):
                        self._send(200, self.service.sandbox.snapshots["mes"])
                    elif self.path.startswith("/sandbox/v1/operations/"):
                        operation_id = self.path.rsplit("/", 1)[-1]
                        self._send(200, self.service.sandbox.operation(operation_id))
                    elif self.path.startswith("/sandbox/v1/audit/"):
                        correlation_id = self.path.rsplit("/", 1)[-1]
                        self._send(200, {"events": self.service.sandbox.audit(correlation_id)})
                    else:
                        self._send(404, {"error": "NOT_FOUND"})
                except ValueError as exc:
                    self._send(404, {"error": str(exc)})

            def do_POST(self) -> None:  # noqa: N802
                try:
                    payload = self._json_body()
                    if self.path == "/sandbox/v1/commands":
                        ack = self.service.sandbox.submit(CanonicalCommand.model_validate(payload))
                        self._send(202, ack.model_dump(mode="json"))
                    elif self.path == "/youjie/v1/callbacks":
                        receipt = self.service.sandbox.receive_callback(
                            ExecutionCallback.model_validate(payload)
                        )
                        self._send(200, receipt.model_dump(mode="json"))
                    else:
                        self._send(404, {"error": "NOT_FOUND"})
                except IdempotencyConflict as exc:
                    self._send(409, {"error": "IDEMPOTENCY_CONFLICT", "message": str(exc)})
                except (ValueError, KeyError) as exc:
                    self._send(422, {"error": "CONTRACT_REJECTED", "message": str(exc)})

        return Handler


class SandboxHttpClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            return exc.code, payload

    def health(self) -> dict[str, Any]:
        status, payload = self._request("GET", "/health")
        if status != 200:
            raise RuntimeError(payload)
        return payload

    def snapshot(self, target: str, scenario_id: str) -> dict[str, Any]:
        status, payload = self._request("GET", f"/sandbox/v1/{target}/snapshots/{scenario_id}")
        if status != 200:
            raise RuntimeError(payload)
        return payload

    def submit(self, command: CanonicalCommand) -> tuple[int, TransportAck | dict[str, Any]]:
        status, payload = self._request("POST", "/sandbox/v1/commands", command.model_dump(mode="json"))
        return status, TransportAck.model_validate(payload) if status == 202 else payload

    def callback(self, callback: ExecutionCallback) -> tuple[int, CallbackReceipt | dict[str, Any]]:
        status, payload = self._request("POST", "/youjie/v1/callbacks", callback.model_dump(mode="json"))
        return status, CallbackReceipt.model_validate(payload) if status == 200 else payload

    def audit(self, correlation_id: str) -> list[dict[str, Any]]:
        status, payload = self._request("GET", f"/sandbox/v1/audit/{correlation_id}")
        if status != 200:
            raise RuntimeError(payload)
        return payload["events"]


def callback_for(
    command: CanonicalCommand,
    ack: TransportAck,
    *,
    event_id: str,
    sequence: int,
    status: BusinessStatus,
    source_revision_after: str,
    target_record_ids: list[str] | None = None,
    changed_entities: list[str] | None = None,
    error_code: str | None = None,
) -> ExecutionCallback:
    errors = [] if error_code is None else [
        IntegrationError(code=error_code, message="Sandbox-injected business outcome", retryable=False)
    ]
    return ExecutionCallback(
        event_id=event_id,
        source=f"urn:youjie:{command.target_system.value}:{command.profile.value}",
        command_id=command.command_id,
        correlation_id=command.correlation_id,
        operation_id=ack.operation_id,
        sequence=sequence,
        business_status=status,
        scenario_hash=command.scenario_hash,
        plan_hash=command.plan_hash,
        source_revision_after=source_revision_after,
        occurred_at=command.created_at,
        target_record_ids=target_record_ids or [],
        changed_entities=changed_entities or [],
        errors=errors,
    )
