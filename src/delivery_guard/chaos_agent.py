"""Seeded, bounded incident generator for reproducible resilience drills."""

from __future__ import annotations

import random

from delivery_guard.models import Incident, IncidentKind, Scenario, StrictModel


class DrillEvent(StrictModel):
    seed: int
    communication_channel: str
    subject: str
    body: str
    incident: Incident
    simulated_fields: list[str]
    safety_boundary: str


class ChaosDrillAgent:
    """Proposes valid incidents; it cannot solve, approve, or execute actions."""

    kinds = tuple(IncidentKind)

    def generate(self, scenario: Scenario, seed: int) -> DrillEvent:
        rng = random.Random(seed)
        kind = self.kinds[seed % len(self.kinds)]
        source_ref = f"synthetic://chaos-drill/{seed}"
        payload: dict = {
            "incident_id": f"inc_drill_{seed}",
            "kind": kind,
            "description": "",
            "source_type": "synthetic_chaos_drill",
            "source_ref": source_ref,
        }

        if kind in {IncidentKind.SUPPLIER_DELAY, IncidentKind.SUPPLIER_SHUTDOWN}:
            source = rng.choice([item for item in scenario.supplier_sources if item.enabled])
            payload["target_id"] = source.source_id
            if kind == IncidentKind.SUPPLIER_DELAY:
                payload["delay_hours"] = rng.choice([24, 48, 72])
                detail = f"交付窗口预计后移 {payload['delay_hours']} 小时"
            else:
                detail = "本规划周期内暂停供货"
            subject = f"供应异常演练：{source.source_id}"
            body = f"供应商协同群通知：{source.source_id} 因模拟上游故障，{detail}。请评估受影响订单。"
            channel = rng.choice(["supplier_email", "procurement_chat"])
        elif kind == IncidentKind.INVENTORY_LOSS:
            entry = rng.choice([item for item in scenario.inventory if item.available > 0])
            payload["target_id"] = entry.item_id
            payload["loss_quantity"] = rng.randint(1, max(1, min(entry.available, entry.available // 3 or 1)))
            subject = f"库存盘点差异：{entry.item_id}"
            body = f"仓库群消息：复盘发现 {entry.item_id} 有 {payload['loss_quantity']} 件模拟账实差异，请冻结并重算。"
            channel = "warehouse_chat"
        elif kind == IncidentKind.LINE_OUTAGE:
            line = rng.choice(scenario.production_lines)
            start = rng.choice(list(range(0, max(4, scenario.horizon_hours - 12), 4)))
            duration = rng.choice([4, 8, 12])
            payload.update(target_id=line.line_id, start_hour=start, end_hour=min(start + duration, scenario.horizon_hours))
            subject = f"MES 模拟停线：{line.line_id}"
            body = f"MES 演练告警：{line.line_id} 在第 {start}–{payload['end_hour']} 小时不可用，不下发真实控制指令。"
            channel = "mes_alarm"
        else:
            order = rng.choice(scenario.orders)
            payload["target_id"] = order.order_id
            payload["quantity_delta"] = rng.choice([20, 40, 60, 100])
            subject = f"需求变更演练：{order.order_id}"
            body = f"销售群消息：客户模拟追加 {payload['quantity_delta']} 台至 {order.order_id}，原交期暂不变，请评估可承诺量。"
            channel = "sales_chat"

        payload["description"] = body
        incident = Incident.model_validate(payload)
        return DrillEvent(
            seed=seed,
            communication_channel=channel,
            subject=subject,
            body=body,
            incident=incident,
            simulated_fields=[
                "incident occurrence",
                "message wording",
                "severity",
                "source timestamp",
            ],
            safety_boundary="演练事件只进入仿真副本；不能审批、写回 ERP/MES 或控制设备。",
        )
