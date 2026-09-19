"""Shared executable skill contracts. One orchestrator, not five fake agents."""
from copy import deepcopy

SKILLS = [
    {"id":"impact", "name":"异常影响研判", "version":"1.0", "tools":["query_order","query_quality_stock"],
     "inputs":["供应商消息","订单X","物料快照"], "steps":["核对消息中的物料与时长","查询订单和可用库存","标出缺口与待核实项"],
     "output":"受影响订单与物料缺口", "boundary":"快照不等于现场盘点"},
    {"id":"knowledge", "name":"经验检索与替代核验", "version":"1.0", "tools":["retrieve_authorization"],
     "inputs":["当前订单范围","登记邮件、会议纪要、工单"], "steps":["读取授权范围内资料","核对技术、客户批准与批次","缺证据则追问，收到回复后重新核验"],
     "output":"带出处的结论或具体补证问题", "boundary":"历史可用不等于本次批准"},
    {"id":"supply", "name":"应急供货调查", "version":"1.0", "tools":["query_delivery"],
     "inputs":["物料缺口","已合格来源"], "steps":["比较常规、区域、应急来源","读取到货与增量报价","把供货条件交给求解器"],
     "output":"来源、报价、到货时间", "boundary":"模拟供货目录，不联系真实供应商"},
    {"id":"decision", "name":"恢复方案决策", "version":"1.0", "tools":["solve_recovery"],
     "inputs":["已核验物料","供货条件","人指定的预算"], "steps":["建立物料、产能与交期约束","CP-SAT求解并独立校验","比较成本与延期，等待人决策"],
     "output":"三案、甘特图和成本交期", "boundary":"模型不能宣布方案可行或自动批准"},
    {"id":"execution", "name":"执行跟踪与重规划", "version":"1.0", "tools":["erp_execute","mes_execute","execution_poll"],
     "inputs":["有效审批","当前计划版本"], "steps":["写入测试系统草稿并回读","人查看执行状态","变化作废旧审批，重新核对"],
     "output":"单据ID、状态回流与重新规划", "boundary":"测试实例，不控制设备、不做库存过账"},
]


def skill_for(tool):
    return next((deepcopy(s) for s in SKILLS if tool in s["tools"]), None)


def harness_view(s):
    """Derive display from this run's events; pending never means executed."""
    trace=s.get("trace", [])
    executed={t.get("tool") for t in trace if t.get("node")=="execute_tool"}
    items=[]
    for skill in SKILLS:
        status="pending"
        if set(skill["tools"]) & executed: status="done"
        if skill["id"]=="supply" and s.get("supply_not_needed") and "query_delivery" not in executed: status="skipped"
        if skill["id"]=="knowledge" and s.get("status")=="awaiting_evidence": status="waiting_human"
        if skill["id"]=="decision" and s.get("plans"): status="waiting_human" if not s.get("approval") else "done"
        if skill["id"]=="execution" and s.get("execution"): status="monitoring"
        if skill["id"]=="execution" and s.get("status")=="needs_reconciliation": status="waiting_human"
        items.append({**deepcopy(skill),"status":status})
    return {"version":"1.0", "orchestrator":"LangGraph · 单一编排Agent", "skills":items,
            "human_mode":"in_the_loop" if s.get("status") in {"awaiting_evidence","awaiting_approval","needs_reconciliation","needs_input"} else
                         "on_the_loop" if s.get("execution") else "agent_running",
            "shortfall":s.get("qualification",{}).get("shortfall"),
            "trace_sequence":len(trace)}
