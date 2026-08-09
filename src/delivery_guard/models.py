"""Strict domain models and cross-entity validation for 有界."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ItemType(StrEnum):
    RAW_MATERIAL = "raw_material"
    COMPONENT = "component"
    FINISHED_GOOD = "finished_good"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"


class IncidentKind(StrEnum):
    SUPPLIER_DELAY = "supplier_delay"
    SUPPLIER_SHUTDOWN = "supplier_shutdown"
    INVENTORY_LOSS = "inventory_loss"
    LINE_OUTAGE = "line_outage"
    DEMAND_SURGE = "demand_surge"


class WorkflowState(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    ANALYZED = "analyzed"
    SOLVED = "solved"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ORDERS_GENERATED = "orders_generated"
    STALE = "stale"


class SourceRecord(StrictModel):
    source_id: str
    source_type: str
    source_ref: str
    license: str
    derived_fields: list[str] = Field(default_factory=list)
    generated_rule: str | None = None


class Provenance(StrictModel):
    as_of: str
    license: str
    sources: list[SourceRecord]
    derived_fields: list[str]
    seed: int


class Item(StrictModel):
    item_id: str
    item_type: ItemType
    name: str
    unit: str
    safety_stock: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_prefix(self) -> "Item":
        expected = "prd_" if self.item_type == ItemType.FINISHED_GOOD else "mat_"
        if not self.item_id.startswith(expected):
            raise ValueError(f"{self.item_type} item_id must start with {expected}")
        return self


class BomLine(StrictModel):
    parent_item_id: str
    component_item_id: str
    quantity: int = Field(gt=0)


class Inventory(StrictModel):
    item_id: str
    location_id: str
    on_hand: int = Field(ge=0)
    reserved: int = Field(default=0, ge=0)
    quality_hold: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_available(self) -> "Inventory":
        if not self.location_id.startswith("loc_"):
            raise ValueError("location_id must start with loc_")
        if self.reserved + self.quality_hold > self.on_hand:
            raise ValueError("reserved + quality_hold cannot exceed on_hand")
        return self

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved - self.quality_hold


class Supplier(StrictModel):
    supplier_id: str
    name: str
    risk_score: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def validate_prefix(self) -> "Supplier":
        if not self.supplier_id.startswith("sup_"):
            raise ValueError("supplier_id must start with sup_")
        return self


class SupplierSource(StrictModel):
    source_id: str
    supplier_id: str
    item_id: str
    lead_time_hours: int = Field(ge=0)
    max_quantity: int = Field(ge=0)
    unit_cost: int = Field(ge=0)
    incremental_unit_cost: int | None = Field(default=None, ge=0)
    committed_quantity: int = Field(default=0, ge=0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_prefixes(self) -> "SupplierSource":
        if not self.source_id.startswith("src_"):
            raise ValueError("source_id must start with src_")
        if self.committed_quantity > self.max_quantity:
            raise ValueError("committed_quantity cannot exceed max_quantity")
        return self

    @property
    def recovery_unit_cost(self) -> int:
        return self.unit_cost if self.incremental_unit_cost is None else self.incremental_unit_cost


class TimeWindow(StrictModel):
    start_hour: int = Field(ge=0)
    end_hour: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_order(self) -> "TimeWindow":
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be greater than start_hour")
        return self

    def overlaps(self, start: int, end: int) -> bool:
        return start < self.end_hour and end > self.start_hour


class ProductionLine(StrictModel):
    line_id: str
    line_type: str
    unavailable_windows: list[TimeWindow] = Field(default_factory=list)
    available_windows: list[TimeWindow] = Field(default_factory=list)
    incremental_cost_per_batch: int = Field(default=0, ge=0)
    overtime: bool = False

    @model_validator(mode="after")
    def validate_line(self) -> "ProductionLine":
        if not self.line_id.startswith("line_"):
            raise ValueError("line_id must start with line_")
        for label, raw_windows in (
            ("unavailable", self.unavailable_windows),
            ("available", self.available_windows),
        ):
            windows = sorted(raw_windows, key=lambda window: window.start_hour)
            for left, right in zip(windows, windows[1:]):
                if left.end_hour > right.start_hour:
                    raise ValueError(f"overlapping {label} windows on {self.line_id}")
        return self

    def permits(self, start: int, end: int) -> bool:
        if any(window.overlaps(start, end) for window in self.unavailable_windows):
            return False
        if not self.available_windows:
            return True
        return any(start >= window.start_hour and end <= window.end_hour for window in self.available_windows)


class RouteOperation(StrictModel):
    operation_id: str
    product_id: str
    sequence: int = Field(gt=0)
    eligible_line_types: list[str] = Field(min_length=1)
    batch_size: int = Field(gt=0)
    duration_per_batch_hours: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_prefix(self) -> "RouteOperation":
        if not self.operation_id.startswith("op_"):
            raise ValueError("operation_id must start with op_")
        return self


class CustomerOrder(StrictModel):
    order_id: str
    product_id: str
    quantity: int = Field(gt=0)
    release_hour: int = Field(ge=0)
    due_hour: int = Field(gt=0)
    priority: Priority = Priority.NORMAL
    frozen: bool = False
    customer_name: str | None = None
    order_group_id: str | None = None
    split_allowed: bool = True
    must_ship_complete: bool = False
    late_penalty_per_unit_hour: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "CustomerOrder":
        if not self.order_id.startswith("ord_"):
            raise ValueError("order_id must start with ord_")
        if self.due_hour <= self.release_hour:
            raise ValueError("due_hour must be greater than release_hour")
        return self


class Scenario(StrictModel):
    scenario_id: str
    scenario_version: int = Field(default=1, gt=0)
    horizon_hours: int = Field(gt=0)
    currency: str = "CNY"
    provenance: Provenance
    items: list[Item]
    bom: list[BomLine]
    inventory: list[Inventory]
    suppliers: list[Supplier]
    supplier_sources: list[SupplierSource]
    production_lines: list[ProductionLine]
    route_operations: list[RouteOperation]
    orders: list[CustomerOrder]
    profile_recovery_budgets: dict[str, int] = Field(default_factory=dict)

    @staticmethod
    def _unique(values: list[str], label: str) -> None:
        if len(values) != len(set(values)):
            duplicates = sorted({value for value in values if values.count(value) > 1})
            raise ValueError(f"duplicate {label}: {duplicates}")

    @model_validator(mode="after")
    def validate_graph(self) -> "Scenario":
        self._unique([item.item_id for item in self.items], "item_id")
        self._unique([supplier.supplier_id for supplier in self.suppliers], "supplier_id")
        self._unique([source.source_id for source in self.supplier_sources], "source_id")
        self._unique([line.line_id for line in self.production_lines], "line_id")
        self._unique([order.order_id for order in self.orders], "order_id")
        self._unique(
            [f"{operation.product_id}:{operation.operation_id}" for operation in self.route_operations],
            "product operation_id",
        )
        self._unique(
            [f"{entry.item_id}:{entry.location_id}" for entry in self.inventory],
            "inventory item/location",
        )

        item_map = {item.item_id: item for item in self.items}
        supplier_ids = {supplier.supplier_id for supplier in self.suppliers}
        line_types = {line.line_type for line in self.production_lines}

        for line in self.bom:
            if line.parent_item_id not in item_map or line.component_item_id not in item_map:
                raise ValueError(f"dangling BOM reference: {line}")
            if line.parent_item_id == line.component_item_id:
                raise ValueError(f"self-referential BOM: {line.parent_item_id}")
            if item_map[line.parent_item_id].item_type == ItemType.RAW_MATERIAL:
                raise ValueError("raw materials cannot be BOM parents")

        graph: dict[str, list[str]] = {item.item_id: [] for item in self.items}
        for line in self.bom:
            graph[line.parent_item_id].append(line.component_item_id)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError(f"cyclic BOM detected at {node}")
            if node in visited:
                return
            visiting.add(node)
            for child in graph[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for item_id in graph:
            visit(item_id)

        for entry in self.inventory:
            if entry.item_id not in item_map:
                raise ValueError(f"inventory references unknown item {entry.item_id}")

        for source in self.supplier_sources:
            if source.supplier_id not in supplier_ids:
                raise ValueError(f"source references unknown supplier {source.supplier_id}")
            if source.item_id not in item_map:
                raise ValueError(f"source references unknown item {source.item_id}")
            if item_map[source.item_id].item_type == ItemType.FINISHED_GOOD:
                raise ValueError("supplier sources cannot directly provide finished goods")

        operations_by_product: dict[str, list[RouteOperation]] = {}
        for operation in self.route_operations:
            if operation.product_id not in item_map:
                raise ValueError(f"operation references unknown product {operation.product_id}")
            if item_map[operation.product_id].item_type != ItemType.FINISHED_GOOD:
                raise ValueError("route operations must reference finished goods")
            if not set(operation.eligible_line_types).issubset(line_types):
                raise ValueError(f"operation {operation.operation_id} references unknown line type")
            operations_by_product.setdefault(operation.product_id, []).append(operation)

        for product_id, operations in operations_by_product.items():
            sequences = sorted(operation.sequence for operation in operations)
            if sequences != list(range(1, len(sequences) + 1)):
                raise ValueError(f"route sequence for {product_id} must be contiguous from 1")

        for order in self.orders:
            if order.product_id not in item_map:
                raise ValueError(f"order references unknown product {order.product_id}")
            if item_map[order.product_id].item_type != ItemType.FINISHED_GOOD:
                raise ValueError("orders must reference finished goods")
            if order.product_id not in operations_by_product:
                raise ValueError(f"missing route for product {order.product_id}")
            if order.due_hour > self.horizon_hours:
                raise ValueError(f"order {order.order_id} due_hour exceeds planning horizon")

        for line in self.production_lines:
            for window in [*line.unavailable_windows, *line.available_windows]:
                if window.end_hour > self.horizon_hours:
                    raise ValueError(f"line window exceeds horizon: {line.line_id}")
        for profile, budget in self.profile_recovery_budgets.items():
            if profile not in {"service_first", "balanced", "stability_first"}:
                raise ValueError(f"unknown profile budget: {profile}")
            if budget < 0:
                raise ValueError(f"negative profile budget: {profile}")
        return self


class Incident(StrictModel):
    incident_id: str
    kind: IncidentKind
    target_id: str
    description: str
    delay_hours: int | None = Field(default=None, gt=0)
    loss_quantity: int | None = Field(default=None, gt=0)
    start_hour: int | None = Field(default=None, ge=0)
    end_hour: int | None = Field(default=None, gt=0)
    quantity_delta: int | None = Field(default=None, gt=0)
    source_type: str = "synthetic_fixture"
    source_ref: str = "data/incidents"

    @model_validator(mode="after")
    def validate_incident(self) -> "Incident":
        if not self.incident_id.startswith("inc_"):
            raise ValueError("incident_id must start with inc_")
        required: dict[IncidentKind, tuple[str, ...]] = {
            IncidentKind.SUPPLIER_DELAY: ("delay_hours",),
            IncidentKind.SUPPLIER_SHUTDOWN: (),
            IncidentKind.INVENTORY_LOSS: ("loss_quantity",),
            IncidentKind.LINE_OUTAGE: ("start_hour", "end_hour"),
            IncidentKind.DEMAND_SURGE: ("quantity_delta",),
        }
        missing = [field for field in required[self.kind] if getattr(self, field) is None]
        if missing:
            raise ValueError(f"{self.kind} missing required fields: {missing}")
        if self.kind == IncidentKind.LINE_OUTAGE and self.end_hour <= self.start_hour:
            raise ValueError("line outage end_hour must exceed start_hour")
        return self


class EvidencePath(StrictModel):
    order_id: str
    path: list[str]
    material_id: str | None = None


class ImpactReport(StrictModel):
    scenario_hash: str
    incident_id: str
    affected_orders: list[str]
    affected_resources: list[str]
    material_demand: dict[str, int]
    projected_shortages: dict[str, int]
    evidence_paths: list[EvidencePath]
    notes: list[str]


class ScheduledOperation(StrictModel):
    task_id: str
    order_id: str
    operation_id: str
    line_id: str
    start_hour: int
    end_hour: int
    incremental_cost: int = Field(default=0, ge=0)
    overtime: bool = False


class PurchaseAction(StrictModel):
    source_id: str
    supplier_id: str
    item_id: str
    quantity: int
    arrival_hour: int
    cost: int
    incremental_cost: int = Field(default=0, ge=0)
    committed: bool = False


class OrderOutcome(StrictModel):
    order_id: str
    scheduled: bool
    completion_hour: int | None
    late_hours: int


class FeasibilityEvidence(StrictModel):
    evidence_id: str
    solver_name: str
    solver_version: str
    solver_status: str
    solve_time_ms: int
    scenario_hash: str
    plan_hash: str
    verified: bool
    violations: list[str]
    objective_breakdown: dict[str, int]
    constraint_counts: dict[str, int]


class CandidatePlan(StrictModel):
    plan_id: str
    profile: str
    scenario_hash: str
    scheduled_operations: list[ScheduledOperation]
    purchases: list[PurchaseAction]
    order_outcomes: list[OrderOutcome]
    objective_breakdown: dict[str, int]
    total_score: int
    evidence: FeasibilityEvidence | None = None
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ApprovalDecision(StrictModel):
    approval_id: str
    plan_id: str
    scenario_hash: str
    plan_hash: str
    decision: str
    actor_id: str
    comment: str = Field(min_length=1)
    valid: bool = True


class WorkOrderDraft(StrictModel):
    work_order_id: str
    work_order_type: str
    approved_plan_id: str
    approval_id: str
    scenario_hash: str
    payload: dict[str, Any]
    execution_status: str = "draft_only"


class AuditEvent(StrictModel):
    sequence: int
    from_state: WorkflowState | None
    to_state: WorkflowState
    actor_type: str
    summary: str
    state_hash: str
