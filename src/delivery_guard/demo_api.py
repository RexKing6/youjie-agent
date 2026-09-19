"""Local judge API for live Agent runs and ERP/MES contract evidence.

The service is deliberately localhost-only by default. It loads existing
runtime credentials server-side, never returns them, and exposes only the
bounded competition workflow plus the project-owned contract sandbox.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import tomllib
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from delivery_guard.data import load_scenario
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.integration import (
    ERPNextAdapter,
    ERPNextConfig,
    ERPNextExecutionLedger,
    ERPNextHttpClient,
    ERPNextMapping,
    IntegrationProfile,
    OpenMESAdapter,
    OpenMESConfig,
    OpenMESExecutionLedger,
    OpenMESHttpClient,
    OpenMESMapping,
    build_erpnext_commands,
    build_openmes_command,
    compare_execution_snapshots,
    compare_openmes_snapshots,
    run_partial_failure_demo,
)
from delivery_guard.llm import OpenAICompatibleLanguageModel


ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "data/cases/mendeley_drill"
SECRET_PATH = ROOT / ".streamlit/secrets.toml"
ALLOWED_SECRET_KEYS = {
    "DELIVERY_GUARD_LLM_BASE_URL",
    "DELIVERY_GUARD_LLM_MODEL",
    "DELIVERY_GUARD_API_KEY",
    "DELIVERY_GUARD_ERPNEXT_BASE_URL",
    "DELIVERY_GUARD_ERPNEXT_API_KEY",
    "DELIVERY_GUARD_ERPNEXT_API_SECRET",
    "DELIVERY_GUARD_ERPNEXT_ENVIRONMENT",
    "DELIVERY_GUARD_ERPNEXT_TIMEOUT_SECONDS",
    "DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE",
    "DELIVERY_GUARD_OPENMES_BASE_URL",
    "DELIVERY_GUARD_OPENMES_API_KEY",
    "DELIVERY_GUARD_OPENMES_ENVIRONMENT",
    "DELIVERY_GUARD_OPENMES_TIMEOUT_SECONDS",
    "DELIVERY_GUARD_OPENMES_UPSTREAM_COMMIT",
    "DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE",
}
MODEL_SECRET_KEYS = {
    "DELIVERY_GUARD_LLM_BASE_URL",
    "DELIVERY_GUARD_LLM_MODEL",
    "DELIVERY_GUARD_API_KEY",
}
ALLOWED_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}


def load_runtime_credentials(path: Path = SECRET_PATH) -> None:
    """Load only known model settings without printing or returning values."""
    if not path.exists():
        return
    values = tomllib.loads(path.read_text(encoding="utf-8"))
    for key in ALLOWED_SECRET_KEYS:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            os.environ.setdefault(key, value.strip())


def live_graph_factory() -> DeliveryGuardGraph:
    load_runtime_credentials()
    base_url = os.environ.get("DELIVERY_GUARD_LLM_BASE_URL")
    model_name = os.environ.get("DELIVERY_GUARD_LLM_MODEL")
    api_key = os.environ.get("DELIVERY_GUARD_API_KEY")
    if not base_url or not model_name or not api_key:
        raise RuntimeError("Live 模型配置不完整；请在服务端配置三个 DELIVERY_GUARD 变量。")
    model = OpenAICompatibleLanguageModel(base_url=base_url, model_name=model_name)
    return DeliveryGuardGraph(
        scenario_path=CASE / "scenario.json",
        knowledge_paths=[
            CASE / "customer_sla.md",
            CASE / "procurement_policy.md",
            CASE / "safety_policy.md",
        ],
        model=model,
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
            if key != "__interrupt__"
        }
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class DemoApiApplication:
    def __init__(
        self,
        graph_factory: Callable[[], DeliveryGuardGraph] = live_graph_factory,
    ) -> None:
        self.graph_factory = graph_factory
        self.scenario = load_scenario(CASE / "scenario.json")
        self.sessions: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    @staticmethod
    def contract_manifest() -> dict[str, Any]:
        return {
            "disclosure": "CONTRACT-COMPATIBLE SANDBOX · NON-CERTIFIED · NO LIVE TENANT",
            "evidence_as_of": "2026-08-29",
            "openapi": "/contracts/openapi.yaml",
            "asyncapi": "/contracts/asyncapi.yaml",
            "system_roles": {
                "erp": "企业资源计划系统：订单、BOM、库存、采购与财务等事务主记录。",
                "mes": "制造执行系统：工单、工序、产线、报工、质量与现场执行状态。",
            },
            "vendor_official_evidence": [
                {
                    "vendor": "SAP S/4HANA",
                    "system": "ERP",
                    "official_protocol": "OData V4 over HTTPS；JSON payload；部分更新可用 PATCH，批处理可用 OData batch。",
                    "official_objects": "Purchase Requisition（A_PurchaseRequisitionHeader）与 Purchase Order（PurchaseOrder service）。",
                    "our_mapping": "ERP snapshot → 订单/BOM/库存/供应承诺；审批后 CanonicalCommand → 采购申请与订单风险草稿。",
                    "not_proven": "未取得 S/4HANA tenant、Communication Arrangement 或 SAP 认证；未发送厂商原生 payload。",
                    "links": [
                        {
                            "label": "SAP 官方：Purchase Requisition API",
                            "url": "https://help.sap.com/docs/SAP_S4HANA_CLOUD/bb9f1469daf04bd894ab2167f8132a1a/2905455816dda007e10000000a441470.html",
                        },
                        {
                            "label": "SAP 官方：Purchase Order OData V4",
                            "url": "https://help.sap.com/docs/SAP_S4HANA_CLOUD/0e602d466b99490187fcbb30d1dc897c/c89eec80ec2043d980cb7b8c89e0a00a.html",
                        },
                    ],
                },
                {
                    "vendor": "SAP Digital Manufacturing",
                    "system": "MES/MOM",
                    "official_protocol": "官方同时提供 OData 与 REST API；BTP service key 提供 public-api-endpoint；OAuth 2.0 client credentials。",
                    "official_objects": "BOM、Routing、Work Center、Inventory、Downtime、Activity Confirmation、Integration Messages 等 API。",
                    "our_mapping": "MES snapshot → 产线/工艺/版本；排程草稿与执行结果 → canonical command/callback。",
                    "not_proven": "未取得 SAP DM service instance、service key 或真实工厂主数据。",
                    "links": [
                        {
                            "label": "SAP 官方：Digital Manufacturing APIs",
                            "url": "https://help.sap.com/docs/sap-digital-manufacturing/apis/apis-for-sap-digital-manufacturing",
                        },
                        {
                            "label": "SAP 官方：API Integration 与 OAuth2",
                            "url": "https://help.sap.com/docs/sap-digital-manufacturing/operations-guide/prepare-for-api-integration?ai=true",
                        },
                    ],
                },
                {
                    "vendor": "金蝶云苍穹 / 星瀚风格",
                    "system": "ERP",
                    "official_protocol": "RESTful OpenAPI；JSON；标准 GET/POST/PUT/PATCH/DELETE；另有保存、提交、审核等操作 API、Token 认证与开放事件。",
                    "official_objects": "查询、保存、提交、审核、反审核、下推等业务操作依产品版本与租户元数据定义。",
                    "our_mapping": "业务查询 → canonical ERP snapshot；save/submit 概念 → draft-only command；不调用目标系统 audit/approve。",
                    "not_proven": "未取得金蝶租户、第三方应用授权、表单标识和字段元数据；不是金蝶认证连接器。",
                    "links": [
                        {
                            "label": "金蝶官方：OpenAPI（开放平台）",
                            "url": "https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29",
                        }
                    ],
                },
                {
                    "vendor": "黑湖智造 3.0",
                    "system": "MES",
                    "official_protocol": "官方 3.0 Open 接口平台；HTTPS API；工单接口示例路径为 /med/open/v2/work_order/_doimport。",
                    "official_objects": "物料、工单、报工等接口以官方动态 API 目录和具体 detailId 为准。",
                    "our_mapping": "工单/产能读取与排程变更结果 → canonical MES snapshot/command/callback。",
                    "not_proven": "未取得黑湖企业租户与 Token；当前 canonical payload 不是黑湖原生 payload，也不声称完成互操作认证。",
                    "links": [
                        {
                            "label": "黑湖官方：3.0 Open 接口平台",
                            "url": "https://v3-hw-openapi.blacklake.cn/release",
                        },
                        {
                            "label": "黑湖官方：工单接口示例",
                            "url": "https://v3-hw-openapi.blacklake.cn/document/api?detailId=1686645473258363&url=%2Fmed%2Fopen%2Fv2%2Fwork_order%2F_doimport",
                        },
                    ],
                },
            ],
            "routes": [
                {"method": "GET", "path": "/health", "purpose": "能力与边界"},
                {"method": "GET", "path": "/sandbox/v1/erp/snapshots/{scenario_id}", "purpose": "订单、BOM、库存、供应承诺"},
                {"method": "GET", "path": "/sandbox/v1/mes/snapshots/{scenario_id}", "purpose": "产线、工艺路线与版本"},
                {"method": "POST", "path": "/sandbox/v1/commands", "purpose": "审批后草稿命令；返回 HTTP 202/PENDING"},
                {"method": "POST", "path": "/youjie/v1/callbacks", "purpose": "异步业务执行结果回流"},
                {"method": "GET", "path": "/sandbox/v1/audit/{correlation_id}", "purpose": "命令、ACK、Callback 审计链"},
            ],
            "schemas": [
                "CanonicalCommand",
                "TransportAck",
                "ExecutionCallback",
                "CallbackReceipt",
            ],
        }

    def health(self) -> dict[str, Any]:
        load_runtime_credentials()
        configured = all(os.environ.get(key) for key in MODEL_SECRET_KEYS)
        erpnext_configured = False
        erpnext_status = "not_configured"
        try:
            erpnext_configured = ERPNextConfig.from_environment() is not None
            erpnext_status = "configured" if erpnext_configured else "not_configured"
        except ValueError:
            erpnext_status = "configuration_error"
        openmes_configured = False
        openmes_status = "not_configured"
        try:
            openmes_configured = OpenMESConfig.from_environment() is not None
            openmes_status = "configured" if openmes_configured else "not_configured"
        except ValueError:
            openmes_status = "configuration_error"
        return {
            "status": "ok",
            "service": "youjie_judge_api",
            "live_model_configured": configured,
            "model_name": os.environ.get("DELIVERY_GUARD_LLM_MODEL") if configured else None,
            "secrets_exposed_to_browser": False,
            "scenario_id": self.scenario.scenario_id,
            "erpnext_configured": erpnext_configured,
            "erpnext_status": erpnext_status,
            "openmes_configured": openmes_configured,
            "openmes_status": openmes_status,
        }

    @staticmethod
    def _erpnext_runtime() -> tuple[ERPNextConfig, ERPNextAdapter, ERPNextMapping]:
        load_runtime_credentials()
        config = ERPNextConfig.from_environment()
        if config is None:
            raise RuntimeError("ERPNext 测试实例尚未配置；合同沙箱仍可正常运行。")
        mapping = ERPNextMapping.from_path(ROOT / "data/integrations/erpnext_demo_mapping.json")
        ledger_path = ROOT / ".tmp/erpnext_execution.sqlite3"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        adapter = ERPNextAdapter(
            ERPNextHttpClient(config),
            ledger=ERPNextExecutionLedger(ledger_path),
        )
        return config, adapter, mapping

    def erpnext_status(self) -> dict[str, Any]:
        try:
            config, adapter, _mapping = self._erpnext_runtime()
        except (RuntimeError, ValueError) as exc:
            return {
                "status": "not_configured",
                "message": str(exc),
                "credentials_exposed": False,
            }
        health = adapter.client.health()
        return {
            **health,
            "profile": IntegrationProfile.ERPNEXT.value,
            "base_url_exposed": False,
            "public_host": config.public_host,
            "write_boundary": "Material Request / Work Order drafts only",
        }

    @staticmethod
    def _openmes_runtime() -> tuple[OpenMESConfig, OpenMESAdapter, OpenMESMapping]:
        load_runtime_credentials()
        config = OpenMESConfig.from_environment()
        if config is None:
            raise RuntimeError("OpenMES 测试实例尚未配置；ERPNext 与合同沙箱仍可正常运行。")
        mapping = OpenMESMapping.from_path(ROOT / "data/integrations/openmes_demo_mapping.json")
        ledger_path = ROOT / ".tmp/openmes_execution.sqlite3"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        adapter = OpenMESAdapter(
            OpenMESHttpClient(config),
            ledger=OpenMESExecutionLedger(ledger_path),
        )
        return config, adapter, mapping

    def openmes_status(self) -> dict[str, Any]:
        try:
            config, adapter, _mapping = self._openmes_runtime()
        except (RuntimeError, ValueError) as exc:
            return {
                "status": "not_configured",
                "message": str(exc),
                "credentials_exposed": False,
            }
        health = adapter.client.health()
        return {
            **health,
            "profile": IntegrationProfile.OPENMES.value,
            "base_url_exposed": False,
            "public_host": config.public_host,
            "write_boundary": "approved work-order import only; production and quality readback",
            "device_control": False,
        }

    def run_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_text = str(payload.get("text", "")).strip()
        if len(raw_text) < 8:
            raise ValueError("请输入至少 8 个字符的事故描述。")
        if len(raw_text) > 5000:
            raise ValueError("事故描述不能超过 5000 个字符。")
        session_id = f"session_{uuid4().hex}"
        thread_id = f"judge_{uuid4().hex}"
        graph = self.graph_factory()
        result = graph.start(
            raw_text=raw_text,
            source_ref=f"judge_input:{session_id}",
            replay_key="interactive_live_input",
            thread_id=thread_id,
        )
        with self.lock:
            self.sessions[session_id] = {
                "graph": graph,
                "thread_id": thread_id,
                "result": result,
                "raw_text": raw_text,
            }
        return {
            "session_id": session_id,
            "run_mode": graph.model.mode,
            "model_name": graph.model.model_name,
            "result": json_safe(result),
        }

    @staticmethod
    def _require_current_external_approval(session: dict[str, Any]) -> None:
        if session.get("erpnext_approval_invalidated") or session.get("openmes_approval_invalidated"):
            raise ValueError(
                "旧审批已失效：ERP/MES 事实已变化；必须核对最新事实、重新规划并批准，禁止继续下发。"
            )

    def approve(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        profile = str(payload.get("profile", "balanced"))
        if profile not in {"service_first", "balanced", "stability_first"}:
            raise ValueError("unknown recovery profile")
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError("unknown session_id")
            self._require_current_external_approval(session)
            result = session["result"]
            if result.get("status") != "awaiting_approval":
                raise ValueError("只有 awaiting_approval 状态可以批准。")
            resumed = session["graph"].resume(
                thread_id=session["thread_id"],
                response={
                    "decision": "approve",
                    "profile": profile,
                    "actor_id": "judge_demo_planner",
                    "comment": (
                        "仅批准测试环境中的 draft_only 业务单据；可写入本地 ERPNext 测试实例"
                        "或合同沙箱，但不提交、不删除、不触碰生产租户或真实设备。"
                    ),
                },
            )
            session["result"] = resumed
        return {"session_id": session_id, "result": json_safe(resumed)}

    def run_integration(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        profile_value = str(
            payload.get("profile", IntegrationProfile.KINGDEE_BLACKLAKE.value)
        )
        try:
            profile = IntegrationProfile(profile_value)
        except ValueError as exc:
            raise ValueError("unknown integration profile") from exc
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError("unknown session_id")
            self._require_current_external_approval(session)
            result = session["result"]
            graph = session["graph"]
            if result.get("status") != "completed":
                raise ValueError("只有完成真人审批的结果才能调用 ERP/MES 合同沙箱。")
        report = run_partial_failure_demo(
            self.scenario,
            result,
            profile,
            feedback_graph=graph,
            feedback_thread_id=f"{session_id}-integration-feedback",
        )
        return {
            "session_id": session_id,
            "contract": self.contract_manifest(),
            "report": json_safe(report),
        }

    def run_erpnext_integration(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError("unknown session_id")
            self._require_current_external_approval(session)
            result = session["result"]
            if result.get("status") != "completed":
                raise ValueError("只有完成真人审批的结果才能写入 ERPNext 测试实例。")

        config, adapter, mapping = self._erpnext_runtime()
        health = adapter.client.health()
        before = adapter.execution_snapshot()
        commands = build_erpnext_commands(
            result,
            mapping,
            expected_source_revision=before["source_revision"],
        )
        executions = [adapter.execute(command) for command in commands]
        after = adapter.execution_snapshot()
        watch_scope: dict[str, list[str]] = {"Material Request": [], "Work Order": []}
        for execution in executions:
            for record in execution.records:
                watch_scope.setdefault(record.doctype, []).append(record.name)
        feedback_baseline = adapter.execution_snapshot(watch_scope)
        referenced_commitments = [
            item
            for command in commands
            for item in command.payload.get("referenced_commitments", [])
        ]
        work_order_records = [
            record
            for execution in executions
            for record in execution.records
            if record.doctype == "Work Order"
        ]
        schedule_documents = [
            document
            for command in commands
            for document in command.payload.get("documents", [])
            if document.get("doctype") == "Work Order"
        ]
        if len(work_order_records) != len(schedule_documents):
            raise RuntimeError("ERPNext Work Order response cannot be mapped to approved schedule documents")
        production_item_to_order = {
            production_item: order_id
            for order_id, production_item in mapping.order_to_production_item.items()
        }
        erpnext_links = [
            {
                "order_id": production_item_to_order[document["production_item"]],
                "erpnext_work_order": record.name,
                "production_item": document["production_item"],
                "qty": document["qty"],
            }
            for record, document in zip(work_order_records, schedule_documents, strict=True)
        ]
        with self.lock:
            session["erpnext_baseline"] = feedback_baseline
            session["erpnext_watch_scope"] = watch_scope
            session["erpnext_command_ids"] = [command.command_id for command in commands]
            session["erpnext_approval_invalidated"] = False
            session["erpnext_links"] = erpnext_links
        return {
            "session_id": session_id,
            "mode": "real_erpnext_test_instance",
            "disclosure": "REAL ERPNEXT TEST INSTANCE · DRAFT ONLY · NOT PRODUCTION",
            "health": health,
            "environment": config.environment,
            "public_host": config.public_host,
            "snapshot_before": {
                "source_revision": before["source_revision"],
                "content_hash": before["content_hash"],
            },
            "commands": [json_safe(command) for command in commands],
            "executions": [json_safe(execution) for execution in executions],
            "referenced_commitments": referenced_commitments,
            "feedback_watch_scope": watch_scope,
            "erpnext_links": erpnext_links,
            "snapshot_after": {
                "source_revision": after["source_revision"],
                "content_hash": after["content_hash"],
            },
            "authorized_change": compare_execution_snapshots(before, after),
            "safety": {
                "draft_only": True,
                "submit": False,
                "cancel": False,
                "delete": False,
                "native_approval": False,
                "device_control": False,
                "credentials_exposed": False,
            },
        }

    def run_openmes_integration(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError("unknown session_id")
            self._require_current_external_approval(session)
            result = session["result"]
            erpnext_links = session.get("erpnext_links")
            if result.get("status") != "completed":
                raise ValueError("只有完成真人审批的结果才能写入 OpenMES 测试实例。")
            if not erpnext_links:
                raise ValueError("请先写入 ERPNext，并取得本次真实 Work Order 编号。")

        config, adapter, mapping = self._openmes_runtime()
        health = adapter.client.health()
        watched_order_nos = [str(item["erpnext_work_order"]) for item in erpnext_links]
        before = adapter.execution_snapshot(watched_order_nos)
        command = build_openmes_command(
            result,
            mapping,
            erpnext_links,
            expected_source_revision=before["source_revision"],
        )
        execution = adapter.execute(command)
        after = adapter.execution_snapshot(watched_order_nos)
        with self.lock:
            session["openmes_baseline"] = after
            session["openmes_watch_order_nos"] = watched_order_nos
            session["openmes_command_id"] = command.command_id
            session["openmes_approval_invalidated"] = False
        return {
            "session_id": session_id,
            "mode": "real_openmes_test_instance",
            "disclosure": "REAL OPENMES TEST INSTANCE · WORK-ORDER IMPORT/READ ONLY · NOT PRODUCTION",
            "health": health,
            "environment": config.environment,
            "public_host": config.public_host,
            "upstream_commit": config.upstream_commit,
            "source_system": "ERPNext",
            "source_links": erpnext_links,
            "snapshot_before": {
                "source_revision": before["source_revision"],
                "content_hash": before["content_hash"],
                "missing_order_nos": before["missing_order_nos"],
            },
            "command": json_safe(command),
            "execution": json_safe(execution),
            "snapshot_after": {
                "source_revision": after["source_revision"],
                "content_hash": after["content_hash"],
                "missing_order_nos": after["missing_order_nos"],
            },
            "authorized_change": compare_openmes_snapshots(before, after),
            "safety": {
                "work_order_import": True,
                "production_readback": True,
                "quality_readback": True,
                "line_start_stop": False,
                "machine_command": False,
                "opc_ua_write": False,
                "modbus_write": False,
                "mqtt_command": False,
                "credentials_exposed": False,
            },
        }

    def check_openmes_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError("unknown session_id")
            baseline = session.get("openmes_baseline")
            watched_order_nos = session.get("openmes_watch_order_nos")
            result = session["result"]
            if not baseline or not watched_order_nos:
                raise ValueError("请先把 ERPNext 工单同步到 OpenMES，再检查执行回流。")
        _config, adapter, _mapping = self._openmes_runtime()
        current = adapter.execution_snapshot(watched_order_nos)
        delta = compare_openmes_snapshots(baseline, current)
        approval = (result.get("workflow") or {}).get("approval") or {}
        with self.lock:
            if delta["changed"]:
                session["openmes_approval_invalidated"] = True
            approval_invalidated = bool(session.get("openmes_approval_invalidated"))
            if delta["changed"]:
                session["openmes_baseline"] = current
        return {
            "session_id": session_id,
            "mode": "real_openmes_feedback_poll",
            "delta": delta,
            "records": current["records"],
            "reconciliation": {
                "status": "awaiting_reconciliation" if approval_invalidated else "no_external_change",
                "previous_approval_id": approval.get("approval_id"),
                "previous_approval_valid": not approval_invalidated,
                "new_commands_blocked": approval_invalidated,
                "work_orders": [] if approval_invalidated else result.get("work_orders", []),
                "reason": (
                    "OpenMES work-order status, produced quantity, or completion revision changed; "
                    "refresh ERP/MES facts and re-run deterministic planning before a new approval."
                    if approval_invalidated
                    else "No OpenMES execution change since the imported work-order baseline."
                ),
            },
            "snapshot": {
                "source_revision": current["source_revision"],
                "content_hash": current["content_hash"],
            },
        }

    def check_erpnext_feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id", ""))
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError("unknown session_id")
            baseline = session.get("erpnext_baseline")
            watch_scope = session.get("erpnext_watch_scope")
            result = session["result"]
            if not baseline:
                raise ValueError("请先完成一次 ERPNext 草稿写入，再检查执行回流。")
        _config, adapter, _mapping = self._erpnext_runtime()
        current = adapter.execution_snapshot(watch_scope)
        delta = compare_execution_snapshots(baseline, current)
        approval = (result.get("workflow") or {}).get("approval") or {}
        with self.lock:
            if delta["changed"]:
                session["erpnext_approval_invalidated"] = True
            approval_invalidated = bool(session.get("erpnext_approval_invalidated"))
        reconciliation = {
            "status": "awaiting_reconciliation" if approval_invalidated else "no_external_change",
            "previous_approval_id": approval.get("approval_id"),
            "previous_approval_valid": not approval_invalidated,
            "new_commands_blocked": approval_invalidated,
            "work_orders": [] if approval_invalidated else result.get("work_orders", []),
            "reason": (
                "ERPNext Work Order / Job Card / Material Request revision changed; "
                "refresh facts and re-run deterministic planning before a new approval."
                if approval_invalidated
                else "No ERPNext execution change since the authorized write baseline."
            ),
        }
        if delta["changed"]:
            with self.lock:
                session["erpnext_baseline"] = current
        return {
            "session_id": session_id,
            "mode": "real_erpnext_feedback_poll",
            "delta": delta,
            "reconciliation": reconciliation,
            "snapshot": {
                "source_revision": current["source_revision"],
                "content_hash": current["content_hash"],
            },
        }


class DemoApiService:
    def __init__(
        self,
        application: DemoApiApplication | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.application = application or DemoApiApplication()
        self.server = ThreadingHTTPServer((host, port), self._handler_type())
        self.server.demo_application = self.application  # type: ignore[attr-defined]

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def serve_forever(self) -> None:
        self.server.serve_forever()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    @staticmethod
    def _handler_type() -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            server_version = "YoujieJudgeApi/1.0"

            @property
            def application(self) -> DemoApiApplication:
                return self.server.demo_application  # type: ignore[attr-defined]

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def _cors(self) -> None:
                origin = self.headers.get("Origin")
                if origin in ALLOWED_ORIGINS:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def _send_json(self, status: int, payload: Any) -> None:
                body = json.dumps(json_safe(payload), ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, path: Path, content_type: str) -> None:
                body = path.read_bytes()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json_body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 100_000:
                    raise ValueError("invalid request body length")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request body must be a JSON object")
                return payload

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    self._send_json(200, self.application.health())
                elif self.path == "/api/v1/contracts":
                    self._send_json(200, self.application.contract_manifest())
                elif self.path == "/api/v1/erpnext/status":
                    self._send_json(200, self.application.erpnext_status())
                elif self.path == "/api/v1/openmes/status":
                    self._send_json(200, self.application.openmes_status())
                elif self.path == "/contracts/openapi.yaml":
                    self._send_file(ROOT / "contracts/openapi.yaml", "application/yaml; charset=utf-8")
                elif self.path == "/contracts/asyncapi.yaml":
                    self._send_file(ROOT / "contracts/asyncapi.yaml", "application/yaml; charset=utf-8")
                else:
                    self._send_json(404, {"error": "NOT_FOUND"})

            def do_POST(self) -> None:  # noqa: N802
                try:
                    payload = self._json_body()
                    if self.path == "/api/v1/agent/run":
                        self._send_json(200, self.application.run_agent(payload))
                    elif self.path == "/api/v1/agent/approve":
                        self._send_json(200, self.application.approve(payload))
                    elif self.path == "/api/v1/integration/run":
                        self._send_json(200, self.application.run_integration(payload))
                    elif self.path == "/api/v1/integration/erpnext/run":
                        self._send_json(200, self.application.run_erpnext_integration(payload))
                    elif self.path == "/api/v1/integration/erpnext/feedback":
                        self._send_json(200, self.application.check_erpnext_feedback(payload))
                    elif self.path == "/api/v1/integration/openmes/run":
                        self._send_json(200, self.application.run_openmes_integration(payload))
                    elif self.path == "/api/v1/integration/openmes/feedback":
                        self._send_json(200, self.application.check_openmes_feedback(payload))
                    else:
                        self._send_json(404, {"error": "NOT_FOUND"})
                except KeyError as exc:
                    self._send_json(404, {"error": "NOT_FOUND", "message": str(exc)})
                except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                    self._send_json(422, {"error": type(exc).__name__, "message": str(exc)})
                except Exception as exc:  # keep the local demo responsive without leaking internals
                    self._send_json(500, {"error": type(exc).__name__, "message": str(exc)})

        return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    service = DemoApiService(host=args.host, port=args.port)
    health = service.application.health()
    print(
        f"judge API listening on {service.base_url}; "
        f"live_model_configured={health['live_model_configured']}"
    )
    try:
        service.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.server.server_close()


if __name__ == "__main__":
    main()
