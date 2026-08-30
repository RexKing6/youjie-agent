import pytest

from delivery_guard.integration import (
    OpenMESAdapter,
    OpenMESConfig,
    OpenMESExecutionLedger,
    OpenMESHttpClient,
    OpenMESMapping,
    build_openmes_command,
    compare_openmes_snapshots,
)
from delivery_guard.integration.openmes import OpenMESAdapterError


def approved_result():
    return {
        "status": "completed",
        "workflow": {
            "scenario_hash": "a" * 64,
            "approval": {
                "decision": "approve",
                "valid": True,
                "approval_id": "approval_1",
                "plan_id": "plan_1",
                "plan_hash": "b" * 64,
            },
        },
    }


def mapping():
    return OpenMESMapping(
        line_code="YOUJIE-ASSEMBLY",
        scenario_epoch="2026-08-30T08:00:00+08:00",
        order_to_product_type={"ord_1": "PRD-1"},
        order_quantities={"ord_1": 91},
        order_priorities={"ord_1": 100},
    )


class FakeOpenMESClient:
    def __init__(self):
        self.config = OpenMESConfig(base_url="http://127.0.0.1:8090", api_key="test-key")
        self.import_calls = 0
        self.rows = {
            "MFG-WO-1": {
                "order_no": "MFG-WO-1",
                "status": "PENDING",
                "planned_qty": 91.0,
                "produced_qty": 0.0,
                "line_code": "YOUJIE-ASSEMBLY",
                "product_type_code": "PRD-1",
                "completed_at": None,
                "updated_at": "2026-08-30T15:00:00+08:00",
                "evidence_hash": "c" * 64,
            }
        }

    def import_work_orders(self, orders):
        self.import_calls += 1
        assert orders[0]["order_no"] == "MFG-WO-1"
        return {"imported": 1, "updated": 0, "skipped": 0, "errors": []}

    def work_order_snapshot(self, order_nos):
        records = [self.rows[item] for item in order_nos if item in self.rows]
        return {
            "source_revision": "openmes:rev1",
            "content_hash": "d" * 64,
            "records": records,
            "missing_order_nos": sorted(set(order_nos) - set(self.rows)),
        }


def test_openmes_config_is_server_side_and_refuses_remote_http(tmp_path):
    assert OpenMESConfig.from_environment({}) is None
    with pytest.raises(ValueError, match="incomplete"):
        OpenMESConfig.from_environment({"DELIVERY_GUARD_OPENMES_BASE_URL": "http://127.0.0.1:8090"})
    with pytest.raises(ValueError, match="HTTPS"):
        OpenMESConfig(base_url="http://mes.example.com", api_key="secret")
    credential = tmp_path / "openmes.json"
    credential.write_text(
        '{"base_url":"http://127.0.0.1:8090","api_key":"file-secret","environment":"test"}',
        encoding="utf-8",
    )
    loaded = OpenMESConfig.from_environment({
        "DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE": str(credential),
    })
    assert loaded is not None
    assert loaded.api_key == "file-secret"


def test_openmes_http_client_refuses_machine_or_generic_application_paths():
    client = OpenMESHttpClient(OpenMESConfig(base_url="http://127.0.0.1:8090", api_key="test-key"))
    with pytest.raises(OpenMESAdapterError, match="PATH_NOT_ALLOWED"):
        client._request("POST", "/api/v1/lines/1/start", payload={})
    with pytest.raises(OpenMESAdapterError, match="PATH_NOT_ALLOWED"):
        client._request("POST", "/api/v1/machines/1/command", payload={})


def test_build_openmes_command_preserves_erpnext_order_number_and_approval_hashes():
    command = build_openmes_command(
        approved_result(),
        mapping(),
        [{"order_id": "ord_1", "erpnext_work_order": "MFG-WO-1"}],
        expected_source_revision="openmes:before",
    )
    order = command.payload["orders"][0]
    assert order["order_no"] == "MFG-WO-1"
    assert order["line_code"] == "YOUJIE-ASSEMBLY"
    assert order["planned_qty"] == 91
    assert command.approval_id == "approval_1"
    assert command.scenario_hash == "a" * 64
    assert command.plan_hash == "b" * 64


def test_openmes_execute_imports_then_reads_back_and_deduplicates():
    client = FakeOpenMESClient()
    adapter = OpenMESAdapter(client, ledger=OpenMESExecutionLedger())
    command = build_openmes_command(
        approved_result(),
        mapping(),
        [{"order_id": "ord_1", "erpnext_work_order": "MFG-WO-1"}],
        expected_source_revision="openmes:before",
    )
    first = adapter.execute(command)
    second = adapter.execute(command)
    assert first.imported == 1
    assert first.records[0].status == "PENDING"
    assert second.duplicate is True
    assert client.import_calls == 1


def test_openmes_execute_fails_closed_when_readback_is_missing():
    client = FakeOpenMESClient()
    client.rows = {}
    adapter = OpenMESAdapter(client, ledger=OpenMESExecutionLedger())
    command = build_openmes_command(
        approved_result(),
        mapping(),
        [{"order_id": "ord_1", "erpnext_work_order": "MFG-WO-1"}],
        expected_source_revision="openmes:before",
    )
    with pytest.raises(OpenMESAdapterError, match="OPENMES_READBACK_MISSING"):
        adapter.execute(command)


def test_openmes_feedback_change_invalidates_approval():
    before = {
        "source_revision": "openmes:before",
        "content_hash": "before",
        "records": [{"order_no": "MFG-WO-1", "status": "PENDING", "produced_qty": 0}],
    }
    after = {
        "source_revision": "openmes:after",
        "content_hash": "after",
        "records": [{"order_no": "MFG-WO-1", "status": "IN_PROGRESS", "produced_qty": 10}],
    }
    delta = compare_openmes_snapshots(before, after)
    assert delta["changed"] is True
    assert delta["invalidates_approval"] is True
    assert delta["changed_entities"] == ["openmes_work_order:MFG-WO-1"]
