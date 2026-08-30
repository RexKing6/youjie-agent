from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from delivery_guard.integration import BusinessStatus
from delivery_guard.integration.erpnext import (
    ERPNextAdapter,
    ERPNextAdapterError,
    ERPNextConfig,
    ERPNextExecutionLedger,
    ERPNextHttpClient,
    ERPNextMapping,
    build_erpnext_commands,
    compare_execution_snapshots,
)
from delivery_guard.integration.ledger import IdempotencyConflict


ROOT = Path(__file__).resolve().parents[1]


class FakeERPNext:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, dict]] = {
            "Material Request": {},
            "Work Order": {},
            "Job Card": {},
        }
        self.post_count = 0
        self.authorization_headers: list[str | None] = []
        self.fail_post_number: int | None = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.server.fake_erpnext = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    @staticmethod
    def _handler() -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args) -> None:
                return

            @property
            def fake(self) -> "FakeERPNext":
                return self.server.fake_erpnext  # type: ignore[attr-defined]

            def send_json(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                self.fake.authorization_headers.append(self.headers.get("Authorization"))
                parsed = urlsplit(self.path)
                if parsed.path == "/api/method/frappe.auth.get_logged_user":
                    self.send_json(200, {"message": "api.integration@example.test"})
                    return
                parts = parsed.path.split("/")
                if len(parts) >= 4 and parts[1:3] == ["api", "resource"]:
                    doctype = unquote(parts[3])
                    if len(parts) == 4:
                        rows = list(self.fake.documents.get(doctype, {}).values())
                        self.send_json(200, {"data": rows})
                        return
                    name = unquote(parts[4])
                    document = self.fake.documents.get(doctype, {}).get(name)
                    if document is None:
                        self.send_json(404, {"exc_type": "DoesNotExistError"})
                    else:
                        self.send_json(200, {"data": document})
                    return
                self.send_json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                self.fake.authorization_headers.append(self.headers.get("Authorization"))
                parsed = urlsplit(self.path)
                parts = parsed.path.split("/")
                if len(parts) != 4 or parts[1:3] != ["api", "resource"]:
                    self.send_json(404, {"error": "not found"})
                    return
                self.fake.post_count += 1
                if self.fake.fail_post_number == self.fake.post_count:
                    self.send_json(422, {"exc_type": "ValidationError", "message": "fixture failure"})
                    return
                doctype = unquote(parts[3])
                length = int(self.headers.get("Content-Length", "0"))
                document = json.loads(self.rfile.read(length))
                prefix = "MAT-MR" if doctype == "Material Request" else "MFG-WO"
                name = f"{prefix}-{self.fake.post_count:05d}"
                stored = {
                    **document,
                    "name": name,
                    "creation": "2026-08-30 12:00:00.000000",
                    "modified": "2026-08-30 12:00:00.000000",
                    "status": "Draft",
                    "docstatus": 0,
                }
                self.fake.documents.setdefault(doctype, {})[name] = stored
                self.send_json(200, {"data": stored})

        return Handler


@pytest.fixture()
def fake_erpnext():
    service = FakeERPNext()
    try:
        yield service
    finally:
        service.close()


@pytest.fixture(scope="module")
def approved_result():
    return json.loads((ROOT / "artifacts/public_data_graph_run.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mapping():
    return ERPNextMapping.from_path(ROOT / "data/integrations/erpnext_demo_mapping.json")


def client_for(service: FakeERPNext) -> ERPNextHttpClient:
    return ERPNextHttpClient(ERPNextConfig(
        base_url=service.base_url,
        api_key="test_key",
        api_secret="test_secret",
        environment="test",
    ))


def test_remote_plain_http_is_rejected():
    with pytest.raises(ValueError, match="must use HTTPS"):
        ERPNextConfig(base_url="http://erp.example.com", api_key="k", api_secret="s")


def test_erpnext_mapping_serializes_datetime_at_transport_boundary(mapping):
    assert mapping.at_hour(8) == "2026-08-30 16:00:00"
    assert mapping.date_at_hour(8) == "2026-08-30"


def test_config_can_load_private_credential_file_without_returning_secret(tmp_path):
    credential_path = tmp_path / "erpnext_credentials.json"
    credential_path.write_text(json.dumps({
        "base_url": "http://127.0.0.1:8088",
        "api_key": "file_key",
        "api_secret": "file_secret",
        "environment": "test",
        "timeout_seconds": 12,
    }), encoding="utf-8")
    config = ERPNextConfig.from_environment({
        "DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE": str(credential_path),
    })
    assert config is not None
    assert config.public_host == "127.0.0.1"
    assert config.timeout_seconds == 12
    assert "file_secret" not in json.dumps({
        "host": config.public_host,
        "environment": config.environment,
    })


def test_direct_environment_overrides_private_credential_file(tmp_path):
    credential_path = tmp_path / "erpnext_credentials.json"
    credential_path.write_text(json.dumps({
        "base_url": "http://127.0.0.1:8088",
        "api_key": "file_key",
        "api_secret": "file_secret",
    }), encoding="utf-8")
    config = ERPNextConfig.from_environment({
        "DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE": str(credential_path),
        "DELIVERY_GUARD_ERPNEXT_API_KEY": "direct_key",
    })
    assert config is not None
    assert config.api_key == "direct_key"
    assert config.api_secret == "file_secret"


def test_health_uses_token_auth_without_returning_secret(fake_erpnext):
    result = client_for(fake_erpnext).health()
    assert result["status"] == "connected"
    assert result["credentials_exposed"] is False
    assert "test_secret" not in json.dumps(result)
    assert fake_erpnext.authorization_headers == ["token test_key:test_secret"]


def test_build_and_execute_real_draft_payloads_is_idempotent(fake_erpnext, approved_result, mapping):
    commands = build_erpnext_commands(
        approved_result,
        mapping,
        expected_source_revision="erpnext:fixture001",
    )
    assert len(commands) == 2
    assert sum(len(command.payload["documents"]) for command in commands) == 4
    commitments = [
        item
        for command in commands
        for item in command.payload.get("referenced_commitments", [])
    ]
    assert commitments == [{
        "source_id": "src_public_seat_q2j",
        "supplier_id": "sup_seat_public",
        "item_id": "mat_q2j",
        "quantity": 217,
        "expected_arrival_hour": 48,
        "committed": True,
        "reason": "existing committed supply; referenced only, no new ERP document",
    }]
    assert all(command.environment == "test" for command in commands)
    assert all(document["docstatus"] == 0 for command in commands for document in command.payload["documents"])

    adapter = ERPNextAdapter(client_for(fake_erpnext), ledger=ERPNextExecutionLedger())
    results = [adapter.execute(command) for command in commands]
    assert [result.business_status for result in results] == [BusinessStatus.APPLIED, BusinessStatus.APPLIED]
    assert [len(result.records) for result in results] == [1, 3]
    assert fake_erpnext.post_count == 4
    assert {record.doctype for result in results for record in result.records} == {"Material Request", "Work Order"}

    duplicates = [adapter.execute(command) for command in commands]
    assert all(result.duplicate for result in duplicates)
    assert fake_erpnext.post_count == 4


def test_same_key_different_payload_fails_closed(fake_erpnext, approved_result, mapping):
    command = build_erpnext_commands(
        approved_result,
        mapping,
        expected_source_revision="erpnext:fixture001",
    )[0]
    ledger = ERPNextExecutionLedger()
    adapter = ERPNextAdapter(client_for(fake_erpnext), ledger=ledger)
    adapter.execute(command)
    mutated_payload = command.model_dump(mode="json", exclude={"payload_hash"})
    mutated_payload["payload"]["documents"][0]["items"][0]["qty"] += 1
    from delivery_guard.integration import CanonicalCommand

    mutated = CanonicalCommand.model_validate(mutated_payload)
    with pytest.raises(IdempotencyConflict):
        adapter.execute(mutated)


def test_partial_creation_is_manual_review_not_blind_retry(fake_erpnext, approved_result, mapping):
    command = build_erpnext_commands(
        approved_result,
        mapping,
        expected_source_revision="erpnext:fixture002",
        created_at="2026-08-30T12:01:00+08:00",
    )[1]
    fake_erpnext.fail_post_number = 2
    adapter = ERPNextAdapter(client_for(fake_erpnext), ledger=ERPNextExecutionLedger())
    with pytest.raises(ERPNextAdapterError) as error:
        adapter.execute(command)
    assert error.value.status == 422
    assert fake_erpnext.post_count == 2
    with pytest.raises(ERPNextAdapterError, match="inspect external records"):
        adapter.execute(command)
    assert fake_erpnext.post_count == 2


def test_execution_feedback_revision_change_invalidates_approval(fake_erpnext):
    adapter = ERPNextAdapter(client_for(fake_erpnext), ledger=ERPNextExecutionLedger())
    fake_erpnext.documents["Work Order"]["MFG-WO-00001"] = {
        "name": "MFG-WO-00001",
        "modified": "2026-08-30 12:00:00.000000",
        "docstatus": 0,
        "status": "Draft",
    }
    before = adapter.execution_snapshot()
    fake_erpnext.documents["Work Order"]["MFG-WO-00001"].update({
        "modified": "2026-08-30 12:10:00.000000",
        "docstatus": 1,
        "status": "In Process",
    })
    fake_erpnext.documents["Job Card"]["JOB-00001"] = {
        "name": "JOB-00001",
        "modified": "2026-08-30 12:10:00.000000",
        "docstatus": 1,
        "status": "Work In Progress",
    }
    after = adapter.execution_snapshot()
    delta = compare_execution_snapshots(before, after)
    assert delta["changed"] is True
    assert delta["invalidates_approval"] is True
    assert "work_order:MFG-WO-00001" in delta["changed_entities"]
    assert "job_card:JOB-00001" in delta["changed_entities"]


def test_scoped_feedback_ignores_unrelated_records(fake_erpnext):
    adapter = ERPNextAdapter(client_for(fake_erpnext), ledger=ERPNextExecutionLedger())
    fake_erpnext.documents["Work Order"].update({
        "MFG-WO-WATCHED": {
            "name": "MFG-WO-WATCHED",
            "modified": "2026-08-30 12:00:00.000000",
            "docstatus": 0,
            "status": "Draft",
        },
        "MFG-WO-UNRELATED": {
            "name": "MFG-WO-UNRELATED",
            "modified": "2026-08-30 12:00:00.000000",
            "docstatus": 0,
            "status": "Draft",
        },
    })
    scope = {"Work Order": ["MFG-WO-WATCHED"], "Material Request": []}
    before = adapter.execution_snapshot(scope)
    fake_erpnext.documents["Work Order"]["MFG-WO-UNRELATED"]["modified"] = (
        "2026-08-30 12:10:00.000000"
    )
    unrelated = adapter.execution_snapshot(scope)
    assert compare_execution_snapshots(before, unrelated)["changed"] is False

    fake_erpnext.documents["Work Order"]["MFG-WO-WATCHED"]["modified"] = (
        "2026-08-30 12:20:00.000000"
    )
    watched = adapter.execution_snapshot(scope)
    delta = compare_execution_snapshots(unrelated, watched)
    assert delta["changed"] is True
    assert delta["changed_entities"] == ["work_order:MFG-WO-WATCHED"]
