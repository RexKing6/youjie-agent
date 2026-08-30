"""Strict project-owned contracts for ERP/MES sandbox interoperability."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from delivery_guard.hashing import stable_hash
from delivery_guard.models import StrictModel


class IntegrationProfile(StrEnum):
    SAP_S4_DM = "sap_s4_dm_contract_profile"
    KINGDEE_BLACKLAKE = "kingdee_blacklake_contract_profile"
    ERPNEXT = "erpnext_open_source_test_profile"
    OPENMES = "openmes_open_source_test_profile"


class TargetSystem(StrEnum):
    ERP = "erp_sandbox"
    MES = "mes_sandbox"
    ERPNEXT = "erpnext_test_tenant"
    OPENMES = "openmes_test_instance"


class TransportStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class BusinessStatus(StrEnum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    APPLIED = "APPLIED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    TIMEOUT_UNKNOWN = "TIMEOUT_UNKNOWN"
    MANUAL_REVIEW = "MANUAL_REVIEW"


TERMINAL_STATUSES = {
    BusinessStatus.APPLIED,
    BusinessStatus.PARTIALLY_APPLIED,
    BusinessStatus.REJECTED,
    BusinessStatus.FAILED,
    BusinessStatus.TIMEOUT_UNKNOWN,
    BusinessStatus.MANUAL_REVIEW,
}


class AdapterCapability(StrictModel):
    profile: IntegrationProfile
    environment: str = "sandbox"
    contract_compatible: bool = True
    certified: bool = False
    live_tenant: bool = False
    sync: bool = True
    async_callback: bool = True
    supports_idempotency: bool = True
    supports_optimistic_lock: bool = True
    supports_partial_success: bool = True
    supports_compensation: str = "draft_only"
    device_control: bool = False
    disclosure: str = "CONTRACT-COMPATIBLE SANDBOX · NON-CERTIFIED · NO LIVE TENANT"


class CanonicalCommand(StrictModel):
    schema_version: str = "youjie.command/v1"
    command_id: str
    correlation_id: str
    causation_id: str
    idempotency_key: str
    profile: IntegrationProfile
    target_system: TargetSystem
    command_type: str
    environment: str = "sandbox"
    scenario_hash: str
    plan_hash: str
    approval_id: str
    expected_source_revision: str
    created_at: str
    payload: dict[str, Any]
    payload_hash: str = ""

    @model_validator(mode="after")
    def validate_command(self) -> "CanonicalCommand":
        if not self.command_id.startswith("cmd_"):
            raise ValueError("command_id must start with cmd_")
        if not self.correlation_id.startswith("cor_"):
            raise ValueError("correlation_id must start with cor_")
        if self.environment not in {"sandbox", "test"}:
            raise ValueError("competition integration may target sandbox or test only")
        if not self.approval_id:
            raise ValueError("approval_id is required")
        if len(self.scenario_hash) != 64 or len(self.plan_hash) != 64:
            raise ValueError("scenario_hash and plan_hash must be SHA-256 hex strings")
        forbidden = ("OPC_UA_WRITE", "METHOD_CALL", "DEVICE_CONTROL", "PLC_WRITE")
        if any(token in self.command_type.upper() for token in forbidden):
            raise ValueError("device control commands are forbidden")
        calculated = stable_hash(self.payload)
        if self.payload_hash and self.payload_hash != calculated:
            raise ValueError("payload_hash does not match payload")
        object.__setattr__(self, "payload_hash", calculated)
        return self


class IntegrationError(StrictModel):
    code: str
    message: str
    retryable: bool = False


class TransportAck(StrictModel):
    schema_version: str = "youjie.ack/v1"
    ack_id: str
    command_id: str
    correlation_id: str
    idempotency_key: str
    operation_id: str
    transport_status: TransportStatus
    business_status: BusinessStatus = BusinessStatus.PENDING
    duplicate: bool = False
    received_at: str
    errors: list[IntegrationError] = Field(default_factory=list)


class ExecutionCallback(StrictModel):
    schema_version: str = "youjie.callback/v1"
    event_id: str
    source: str
    command_id: str
    correlation_id: str
    operation_id: str
    sequence: int = Field(ge=1)
    business_status: BusinessStatus
    scenario_hash: str
    plan_hash: str
    source_revision_after: str
    occurred_at: str
    target_record_ids: list[str] = Field(default_factory=list)
    changed_entities: list[str] = Field(default_factory=list)
    errors: list[IntegrationError] = Field(default_factory=list)
    evidence_hash: str = ""

    @model_validator(mode="after")
    def validate_evidence_hash(self) -> "ExecutionCallback":
        payload = self.model_dump(mode="json", exclude={"evidence_hash"})
        calculated = stable_hash(payload)
        if self.evidence_hash and self.evidence_hash != calculated:
            raise ValueError("callback evidence_hash does not match payload")
        object.__setattr__(self, "evidence_hash", calculated)
        return self


class CallbackReceipt(StrictModel):
    event_id: str
    command_id: str
    operation_id: str
    accepted: bool
    duplicate: bool = False
    stale_sequence: bool = False
    current_business_status: BusinessStatus
    plan_stale: bool = False
