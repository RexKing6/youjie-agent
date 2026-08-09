"""Typed language-Agent context and auditable tool traces."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from delivery_guard.models import StrictModel


class AgentTaskState(StrEnum):
    COLLECTING = "collecting"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY_TO_CONFIRM = "ready_to_confirm"
    CONFIRMED = "confirmed"
    ANALYZED = "analyzed"
    SOLVED = "solved"
    AWAITING_APPROVAL = "awaiting_approval"
    STALE = "stale"
    COMPLETED = "completed"
    REJECTED = "rejected"


class SourceSpan(StrictModel):
    source_ref: str
    quote: str
    field_name: str


class IncidentDraft(StrictModel):
    incident_kind: str | None = None
    target_mention: str | None = None
    resolved_target_id: str | None = None
    delay_hours: int | None = Field(default=None, gt=0)
    loss_quantity: int | None = Field(default=None, gt=0)
    start_hour: int | None = Field(default=None, ge=0)
    end_hour: int | None = Field(default=None, gt=0)
    quantity_delta: int | None = Field(default=None, gt=0)
    confidence: str = "low"
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    required_confirmations: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)
    security_flags: list[str] = Field(default_factory=list)

    def has_source_for(self, field_name: str) -> bool:
        return any(span.field_name == field_name and span.quote.strip() for span in self.source_spans)


class KnowledgeCitation(StrictModel):
    citation_id: str
    document_id: str
    source_ref: str
    section: str
    text: str
    document_hash: str
    score: int = Field(ge=0)
    security_flags: list[str] = Field(default_factory=list)


class AgentMessage(StrictModel):
    role: str
    content: str
    source_ref: str | None = None


class ToolTrace(StrictModel):
    sequence: int = Field(gt=0)
    tool_name: str
    input_summary: dict[str, Any]
    result_summary: dict[str, Any]
    success: bool
    source_refs: list[str] = Field(default_factory=list)


class RecoveryAuthorization(StrictModel):
    allow_beta: bool = False
    beta_max_quantity: int = Field(default=0, ge=0)
    allow_overtime: bool = False
    overtime_max_units: int = Field(default=0, ge=0)
    actor_id: str
    comment: str


class TaskContext(StrictModel):
    task_id: str
    state: AgentTaskState = AgentTaskState.COLLECTING
    messages: list[AgentMessage] = Field(default_factory=list)
    incident_draft: IncidentDraft | None = None
    retrieved_evidence: list[KnowledgeCitation] = Field(default_factory=list)
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    authorization: RecoveryAuthorization | None = None
    scenario_hash: str | None = None
    active_plan_hash: str | None = None
    stale_reason: str | None = None
    model_mode: str = "replay"
    model_name: str = "delivery-guard-replay-v1"

    def add_trace(
        self,
        tool_name: str,
        input_summary: dict[str, Any],
        result_summary: dict[str, Any],
        *,
        success: bool = True,
        source_refs: list[str] | None = None,
    ) -> None:
        self.tool_traces.append(
            ToolTrace(
                sequence=len(self.tool_traces) + 1,
                tool_name=tool_name,
                input_summary=input_summary,
                result_summary=result_summary,
                success=success,
                source_refs=source_refs or [],
            )
        )
