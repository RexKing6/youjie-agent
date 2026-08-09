"""Grounded, deterministic plan explanation content for UI and model prompts."""

from __future__ import annotations

from typing import Any

from delivery_guard.context import KnowledgeCitation


PROFILE_LABELS = {
    "service_first": "保交付",
    "balanced": "平衡方案",
    "stability_first": "少变更",
}


def grounded_plan_explanation(
    summary: dict[str, Any],
    citations: list[KnowledgeCitation],
) -> dict[str, Any]:
    groups = summary["groups"]
    a = groups.get("order_a", {})
    b = groups.get("order_b", {})
    citation_ids = [citation.citation_id for citation in citations]
    return {
        "title": PROFILE_LABELS.get(summary["profile"], summary["profile"]),
        "facts": [
            f"首个交期按时 {summary['first_due_on_time_units']} 台，延期 {summary['first_due_late_units']} 台。",
            f"恢复增量成本 {summary['recovery_cost']} 元，其中加班 {summary['overtime_cost']} 元。",
            f"备选供应商采购 {summary['alternate_supplier_units']} 颗，加班生产 {summary['overtime_units']} 台。",
            f"关键客户 A 按时 {a.get('on_time_units', 0)} 台；普通客户 B 按时 {b.get('on_time_units', 0)} 台。",
        ],
        "citation_ids": citation_ids,
        "boundary": "以上数字来自确定性工具；语言模型不声明可行性。",
    }
