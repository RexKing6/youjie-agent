"""Public failure contract. Diagnostics confer no authority and perform no I/O."""
from __future__ import annotations


# Public messages are authored locally: never echo provider exceptions or input.
RECOVERY = {
    "INPUT_AMBIGUOUS": ("输入信息不足或格式不明确", "补充明确的订单、物料、延期单位和数量，再提交。"),
    "UNSUPPORTED_SCOPE": ("请求超出当前案例支持范围", "核对当前O-208/A1/A2范围；未支持的要求不会被忽略执行。"),
    "MODEL_SCHEMA_INVALID": ("模型或字段校验失败", "保留失败记录，核对输入后重新发起；本次不自动重试或切换离线。"),
    "WIKI_COVERAGE_MISSING": ("Wiki遗漏来源", "检查所选来源覆盖；上一有效Wiki不代表此次刷新成功。"),
    "WIKI_DUPLICATE_SOURCE": ("Wiki重复处理来源", "每份来源仅允许一个处置；核对来源清单后重新整理。"),
    "WIKI_DUPLICATE_SPAN": ("Wiki重复引用片段", "检查重复片段；不将重复内容当成多份证据。"),
    "WIKI_SOURCE_HASH_MISMATCH": ("Wiki来源版本不一致", "核对登记原文版本后重新整理，保留上一有效版本。"),
    "SPAN_NOT_FOUND": ("Wiki引用片段无效", "核对来源版本及片段ID，不能用近似文字替换原文。"),
    "FOLLOWUP_TARGET_MISMATCH": ("模型追问目标不符", "核对当前订单与证据缺口；不按错误目标授予权限。"),
    "EVIDENCE_CONFLICT": ("证据冲突尚未解决", "补充有权方对同范围冲突的明确处理依据。"),
    "STALE_APPROVAL": ("版本或审批已失效", "恢复当前任务并核对变化；必要时重新计算和审批，不重放旧请求。"),
    "EXTERNAL_TIMEOUT_UNKNOWN": ("外部请求结果未知", "先恢复任务并只读检查执行结果；禁止直接再次下单。"),
    "EXTERNAL_PARTIAL": ("外部交付尚未全部完成", "保留已有单号，先只读对账；仅在确认未写入后补未完成步骤。"),
    "READBACK_MISMATCH": ("外部回读与批准计划不一致", "检查原系统单据和关联范围；不要通过修改计划迎合错误回读。"),
    "FEEDBACK_INSUFFICIENT": ("执行反馈需要对账", "核实合格产量、实际耗料及时间来源，补齐后再重算。"),
    "EVIDENCE_INSUFFICIENT": ("资格证据仍有缺口", "按当前问题补充登记依据；达到两次补证上限后暂停。"),
    "REQUEST_INVALID": ("请求未通过校验", "检查字段和任务状态；若已有单号，先恢复并核对，不重复下单。"),
    "SERVICE_UNAVAILABLE": ("服务暂时不可用", "保留记录，恢复任务并核实执行状态后再决定下一步。"),
    "MODEL_UNAVAILABLE": ("模型调用未完成", "检查模型服务与用量记录，再人工决定是否重新开始；不自动重试或切换离线。"),
    "MODEL_RATE_LIMITED": ("在线模型服务限流（HTTP 429）", "稍后检查服务可用性并重新分析；保留输入和材料，不自动重试或切换离线。"),
    "MODEL_QUOTA_EXHAUSTED": ("模型服务商配额不足", "恢复服务商配额后再重新分析；不自动更换模型、凭据或切换离线。"),
    "EXTERNAL_DEPENDENCY_CHANGED": ("外部单据依赖已变化", "先在原系统核对工单、物料和排程变化；不能只填写产量来跳过异常。"),
}


def state_failure(state: dict) -> dict | None:
    """Clarification is not a model error; past rejections do not taint later success."""
    status = state.get("status")
    current = [t for t in state.get("trace", []) if t.get("turn") == state.get("reply_count", 0)]
    rejected = next((t for t in reversed(current) if t.get("candidate_rejected")), None)
    if status == "model_or_validation_error":
        stopped = next((t for t in reversed(current) if t.get("node") == "safe_stop"), {})
        return failure("model_or_validation", state, code=stopped.get("error_code", "MODEL_SCHEMA_INVALID"))
    if rejected and status in {"needs_input", "awaiting_evidence", "paused"}:
        return failure(rejected.get("node", "model"), state, code=rejected.get("error_code", "MODEL_SCHEMA_INVALID"))
    if status == "needs_input":
        unsupported = any(t.get("input_category") == "unsupported" for t in current)
        return failure("understand_reply", state, code="UNSUPPORTED_SCOPE" if unsupported else "INPUT_AMBIGUOUS")
    if status in {"awaiting_evidence", "paused"} and (state.get("qualification") or {}).get("gaps"):
        gaps = state["qualification"]["gaps"]
        return failure("assess_evidence", state, code="EVIDENCE_CONFLICT" if any("conflict" in g for g in gaps) else "EVIDENCE_INSUFFICIENT")
    if status == "needs_reconciliation":
        invalid = (state.get("pending_execution_event") or {}).get("invalid_dependency")
        return failure("execution_feedback", state, code="EXTERNAL_DEPENDENCY_CHANGED" if invalid else "FEEDBACK_INSUFFICIENT")
    return None


def external_records(state: dict | None, *, uncertain_without_state: bool = False) -> dict:
    if state is None:
        value = "unknown" if uncertain_without_state else "none"
        return {"erp": value, "mes": value}
    execution = state.get("execution") or {}
    status = execution.get("status")
    erp = "known" if execution.get("erp_document") else "unknown" if execution.get("erp_command") else "none"
    mes = "known" if execution.get("mes_baseline") or execution.get("mes_result") else "unknown" if execution.get("mes_command") else "none"
    # An unresolved response remains uncertain even when another system is known.
    if status == "mes_outcome_unknown":
        mes = "unknown"
    if status == "erp_outcome_unknown" and not execution.get("erp_document"):
        erp = "unknown"
    return {"erp": erp, "mes": mes}


def failure(stage: str, state: dict | None = None, *, code: str | None = None,
            exc: Exception | None = None, uncertain_without_state: bool = False) -> dict:
    """Prefer explicit categories and recorded write stages; fail conservatively."""
    state = state or None
    execution = (state or {}).get("execution") or {}
    raw = getattr(exc, "code", "") if exc is not None else ""
    # Exact local constants only; arbitrary exception text is never returned.
    if isinstance(exc, ValueError) and not raw:
        raw = str(exc)
    if not isinstance(raw, str):
        raw = ""
    if code not in RECOVERY:
        code = raw if raw in RECOVERY else None
    if code is None and raw in {
        "VALID_HUMAN_APPROVAL_REQUIRED", "APPROVED_PLAN_HASH_MISMATCH", "APPROVED_SCENARIO_HASH_MISMATCH",
        "EXECUTION_APPROVAL_CHANGED", "批准依赖已变化", "任务版本已变化，请刷新；旧回复或审批不能重放",
    }:
        code = "STALE_APPROVAL"
    if code is None and isinstance(raw, str) and raw.startswith(("ERP_READBACK_", "MES_READBACK_", "ERP_PURCHASE_READBACK_")):
        code = "READBACK_MISMATCH"
    if code is None and execution.get("status") in {"erp_outcome_unknown", "mes_outcome_unknown"}:
        code = "EXTERNAL_TIMEOUT_UNKNOWN"
    if code is None and execution.get("status") == "partial_failure":
        code = "EXTERNAL_PARTIAL"
    if code is None and (state or {}).get("status") == "needs_reconciliation":
        invalid = ((state or {}).get("pending_execution_event") or {}).get("invalid_dependency")
        code = "EXTERNAL_DEPENDENCY_CHANGED" if invalid else "FEEDBACK_INSUFFICIENT"
    if code is None:
        code = "REQUEST_INVALID" if isinstance(exc, ValueError) else "SERVICE_UNAVAILABLE"
    title, action = RECOVERY[code]
    return {"stage": stage, "error_code": code, "message": title, "recovery_action": action,
            "retryable": False, "retry_semantics": "same_request_without_review",
            "external_records": external_records(state, uncertain_without_state=uncertain_without_state),
            "run_id": (state or {}).get("run_id"), "revision": (state or {}).get("revision"),
            "trace_sequence": len((state or {}).get("trace", [])),
            "blocked_action": "automatic_retry_or_external_delivery"}
