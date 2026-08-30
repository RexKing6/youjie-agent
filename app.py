"""Streamlit competition demo for the public-data LangGraph workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import altair as alt
import pandas as pd
import streamlit as st

from delivery_guard.chaos_agent import ChaosDrillAgent
from delivery_guard.data import load_scenario
from delivery_guard.evidence import load_evidence_bundle
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.integration import IntegrationProfile, run_partial_failure_demo
from delivery_guard.llm import OpenAICompatibleLanguageModel, ReplayLanguageModel
from delivery_guard.semifinal import load_semifinal_cases, run_infeasible_case


ROOT = Path(__file__).resolve().parent
CASE = ROOT / "data/cases/mendeley_drill"
RAW = ROOT / "data/public/mendeley_automotive/2020_dataset_automotive_production_network.xlsb"
SEMIFINAL_CASES = load_semifinal_cases(CASE / "semifinal_cases.json")
CASE_OPTIONS = [*SEMIFINAL_CASES, "random_drill"]
LIVE_EVAL_PATH = ROOT / "artifacts/live_agent_eval_report.json"
PROFILE_LABELS = {
    "service_first": "保交付",
    "balanced": "平衡方案",
    "stability_first": "少变更",
}
LIVE_LLM_AVAILABLE = all(
    os.environ.get(name)
    for name in (
        "DELIVERY_GUARD_LLM_BASE_URL",
        "DELIVERY_GUARD_LLM_MODEL",
        "DELIVERY_GUARD_API_KEY",
    )
)


def build_graph(mode: str) -> DeliveryGuardGraph:
    if mode == "live":
        base_url = os.environ.get("DELIVERY_GUARD_LLM_BASE_URL")
        model_name = os.environ.get("DELIVERY_GUARD_LLM_MODEL")
        if not base_url or not model_name or not os.environ.get("DELIVERY_GUARD_API_KEY"):
            raise RuntimeError(
                "Live 模式需要 DELIVERY_GUARD_LLM_BASE_URL、DELIVERY_GUARD_LLM_MODEL "
                "和 DELIVERY_GUARD_API_KEY；页面不会采集或保存密钥。"
            )
        model = OpenAICompatibleLanguageModel(base_url=base_url, model_name=model_name)
    else:
        model = ReplayLanguageModel(ROOT / "data/model_replays/mendeley_drill.json")
    return DeliveryGuardGraph(
        scenario_path=CASE / "scenario.json",
        knowledge_paths=[
            CASE / "customer_sla.md",
            CASE / "procurement_policy.md",
            CASE / "safety_policy.md",
        ],
        model=model,
    )


def clear_run() -> None:
    for key in (
        "guard_graph", "graph_result", "thread_id", "drill_event", "run_kind",
        "graph_mode", "active_case_id",
        "integration_report",
    ):
        st.session_state.pop(key, None)


def case_label(case_id: str) -> str:
    if case_id == "random_drill":
        return "随机演练：五类合法事故"
    return SEMIFINAL_CASES[case_id]["label"]


def case_text(case: dict) -> str:
    if case["case_id"] == "source_conflict":
        refs = [
            CASE / "evidence/supplier_email.eml",
            CASE / "evidence/carrier_notice_source.txt",
            CASE / "evidence/mes_snapshot.csv",
        ]
        return "\n\n--- NEXT SOURCE ---\n\n".join(
            path.read_text(encoding="utf-8") for path in refs
        )
    return (ROOT / case["input_ref"]).read_text(encoding="utf-8")


def plan_frame(result: dict, profile: str) -> pd.DataFrame:
    plan = next(item for item in result["plans"] if item["profile"] == profile)
    return pd.DataFrame([
        {
            "订单": task["order_id"],
            "产线": task["line_id"],
            "开始小时": task["start_hour"],
            "结束小时": task["end_hour"],
            "状态": "加班" if task["overtime"] else "正常",
        }
        for task in plan["scheduled_operations"]
    ])


def render_timeline(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.warning("该方案没有可排入的工序。")
        return
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadius=4, height=20)
        .encode(
            x=alt.X("开始小时:Q", title="场景小时"),
            x2="结束小时:Q",
            y=alt.Y("订单:N", title=None),
            color=alt.Color("订单:N", legend=None),
            tooltip=["订单", "产线", "开始小时", "结束小时", "状态"],
        )
        .properties(height=150)
    )
    st.altair_chart(chart, width="stretch")


def comparison_frame(result: dict) -> pd.DataFrame:
    rows = []
    for profile in ("service_first", "balanced", "stability_first"):
        summary = result["plan_summaries"][profile]
        plan = next(item for item in result["plans"] if item["profile"] == profile)
        rows.append({
            "方案": PROFILE_LABELS[profile],
            "首交期按时": summary["first_due_on_time_units"],
            "延期/未按时": summary["first_due_late_units"],
            "应急采购": summary["alternate_supplier_units"],
            "恢复成本": summary["recovery_cost"],
            "排程工序": len(plan["scheduled_operations"]),
            "资源调整": len(plan["purchases"]) + sum(
                int(item["overtime"]) for item in plan["scheduled_operations"]
            ),
            "验证": "通过" if plan["evidence"]["verified"] else "失败",
        })
    return pd.DataFrame(rows)


def all_plan_frame(result: dict) -> pd.DataFrame:
    frames = []
    for profile in ("service_first", "balanced", "stability_first"):
        frame = plan_frame(result, profile)
        frame["方案"] = PROFILE_LABELS[profile]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def render_comparison_gantt(result: dict) -> None:
    frame = all_plan_frame(result)
    if frame.empty:
        st.warning("三个方案都没有可排入的工序。")
        return
    order_sort = sorted(frame["订单"].unique())
    chart = (
        alt.Chart(frame)
        .mark_bar(cornerRadius=3, height=13)
        .encode(
            x=alt.X("开始小时:Q", title="统一场景小时", scale=alt.Scale(domain=[0, 96])),
            x2="结束小时:Q",
            y=alt.Y("订单:N", title=None, sort=order_sort),
            color=alt.Color("订单:N", legend=None),
            opacity=alt.condition(alt.datum["状态"] == "加班", alt.value(1), alt.value(0.76)),
            tooltip=["方案", "订单", "产线", "开始小时", "结束小时", "状态"],
        )
        .properties(height=76)
        .facet(
            row=alt.Row(
                "方案:N",
                title=None,
                sort=["保交付", "平衡方案", "少变更"],
                header=alt.Header(labelFontSize=13, labelFontWeight="bold"),
            )
        )
        .resolve_scale(x="shared", y="shared")
    )
    st.altair_chart(chart, width="stretch")


def render_order_impact_graph(scenario, result: dict) -> None:
    impact = result.get("impact") or {}
    affected = impact.get("affected_orders") or []
    if not affected:
        st.info("该案例没有可视化的受影响订单路径。")
        return
    order_map = {item.order_id: item for item in scenario.orders}
    item_map = {item.item_id: item for item in scenario.items}
    material_ids = sorted({
        item.get("material_id") for item in impact.get("evidence_paths", [])
        if item.get("material_id")
    }) or ["mat_q2j"]
    supplier_id = (impact.get("affected_resources") or ["sup_seat_public"])[0]
    material_id = material_ids[0]
    line_id = scenario.production_lines[0].line_id
    nodes: dict[str, dict] = {
        supplier_id: {"id": supplier_id, "x": 0, "y": 1, "类别": "供应商", "标签": "原供应商"},
        material_id: {"id": material_id, "x": 1, "y": 1, "类别": "物料", "标签": item_map[material_id].name},
        line_id: {"id": line_id, "x": 4, "y": 1, "类别": "产线", "标签": "整车装配线"},
    }
    links = []
    links.append({"x": 0, "y": 1, "x2": 1, "y2": 1})
    for index, order_id in enumerate(affected):
        order = order_map[order_id]
        y = float(index)
        product_id = order.product_id
        nodes[product_id] = {
            "id": product_id, "x": 2, "y": y, "类别": "产品",
            "标签": item_map[product_id].name,
        }
        nodes[order_id] = {
            "id": order_id, "x": 3, "y": y, "类别": "订单",
            "标签": f"{order.customer_name} · {order.quantity}台",
        }
        links.extend([
            {"x": 1, "y": 1, "x2": 2, "y2": y},
            {"x": 2, "y": y, "x2": 3, "y2": y},
            {"x": 3, "y": y, "x2": 4, "y2": 1},
        ])
    node_frame = pd.DataFrame(nodes.values())
    link_frame = pd.DataFrame(links)
    edges = alt.Chart(link_frame).mark_rule(color="#94a3b8", strokeWidth=2).encode(
        x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-0.25, 4.25])),
        x2="x2:Q",
        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-0.55, 2.55])),
        y2="y2:Q",
    )
    points = alt.Chart(node_frame).mark_circle(size=680, stroke="white", strokeWidth=2).encode(
        x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-0.25, 4.25])),
        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-0.55, 2.55])),
        color=alt.Color(
            "类别:N",
            scale=alt.Scale(
                domain=["供应商", "物料", "产品", "订单", "产线"],
                range=["#ef4444", "#f59e0b", "#0ea5e9", "#2563eb", "#14b8a6"],
            ),
            legend=alt.Legend(orient="bottom"),
        ),
        tooltip=["类别", "标签", "id"],
    )
    labels = alt.Chart(node_frame).mark_text(dy=-24, fontSize=11, fontWeight="bold").encode(
        x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-0.25, 4.25])),
        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-0.55, 2.55])),
        text="标签:N",
    )
    st.altair_chart((edges + points + labels).properties(height=270), width="stretch")
    st.caption("所有边由确定性订单/BOM/物料/产线关系生成；悬停可查看稳定ID。LLM无权添加关系。")


st.set_page_config(page_title="有界 · 公开数据供应链演练", page_icon="🛡️", layout="wide")
st.markdown(
    """
<style>
  .block-container {padding-top:.7rem; max-width:1180px;}
  .hero {padding:1rem 1.2rem; border-radius:18px; background:linear-gradient(125deg,#071d2b,#15475a 62%,#176052); color:#f8fafc;}
  .hero h1 {margin:.15rem 0; font-size:1.8rem;}
  .hero p {margin:.2rem 0; color:#c8dce5;}
  .tag {display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#ccfbf1; color:#115e59; font-size:.72rem; font-weight:750;}
  .boundary {padding:.7rem .9rem; border-left:4px solid #f59e0b; background:#fff8e8; color:#854d0e; border-radius:8px;}
  [data-testid="stMetric"] {border:1px solid #d6e2e7; border-radius:12px; padding:10px;}
</style>
<div class="hero">
  <span class="tag">GOAI · AI + 工业制造</span>
  <h1>有界 · 制造供应链异常研判与恢复计划智能体</h1>
  <p>Mendeley 汽车供应链原始行 + 显式模拟事故覆盖层 + LangGraph 人审状态图 + CP-SAT 与独立验证器。</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("运行设置")
    available_modes = ["live", "replay"] if LIVE_LLM_AVAILABLE else ["replay"]
    mode = st.radio(
        "语言模型",
        available_modes,
        format_func=lambda value: (
            "离线 Replay"
            if value == "replay"
            else f"Live · {os.environ.get('DELIVERY_GUARD_LLM_MODEL', 'OpenAI-compatible')}"
        ),
    )
    if not LIVE_LLM_AVAILABLE:
        st.caption("公开版未配置模型密钥，因此仅开放可复现 Replay；密钥不会由页面采集。")
    else:
        st.caption("已配置真实模型，默认使用 Live；Replay 仅用于断网复现与回归。")
    case_id = st.selectbox(
        "复赛验证案例",
        CASE_OPTIONS,
        format_func=case_label,
        on_change=clear_run,
        key="selected_case_id",
    )
    selected_case = SEMIFINAL_CASES.get(case_id)
    if selected_case:
        st.caption(selected_case["purpose"])
    seed = st.number_input(
        "演练 seed",
        min_value=0,
        max_value=99_999_999,
        value=20260810,
        step=1,
        disabled=case_id != "random_drill",
    )
    if case_id == "random_drill":
        st.caption("seed 相同则事件完全一致；连续五个 seed 可覆盖五类事故。")
    if st.button("清空并重新开始", width="stretch"):
        clear_run()
        st.rerun()
    st.divider()
    st.caption("LLM：理解文本与保留证据 span")
    st.caption("LangGraph：规划、工具路由、中断与恢复")
    st.caption("CP-SAT：排产与采购可行性")
    st.caption("Verifier：独立重放全部硬约束")
    st.caption("人：最终批准或驳回")
    st.caption("复赛版：成功、冲突、无解和注入都可一键验证")

lineage = json.loads((CASE / "lineage.json").read_text(encoding="utf-8"))
scenario = load_scenario(CASE / "scenario.json")
data_tab, event_tab, plan_tab, integration_tab, audit_tab = st.tabs(
    ["① 公开数据证据", "② 事故与 Agent", "③ 恢复指挥台", "④ ERP/MES闭环", "⑤ 工具审计"]
)

with data_tab:
    cols = st.columns(4)
    cols[0].metric("原工作簿产品", "28,049")
    cols[1].metric("本案例原始需求行", lineage["integrity"]["selected_demand_rows"])
    cols[2].metric("聚合订单数量", lineage["integrity"]["aggregate_order_sum"])
    cols[3].metric("数量守恒差", lineage["integrity"]["selected_demand_sum"] - lineage["integrity"]["aggregate_order_sum"])
    st.success("工作簿 SHA-256 已核验；217 条公开需求行聚合后仍为 217 台。每条原始工作表行号保存在 lineage.json。")
    st.dataframe(
        pd.DataFrame([
            {
                "聚合产品": product_id,
                "公开 BOM 配置": "+".join(info["bom_signature"]),
                "原始需求行": info["source_row_count"],
                "需求合计": info["sum_of_source_demand"],
            }
            for product_id, info in lineage["derived_aggregates"].items()
        ]),
        width="stretch",
        hide_index=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown("**公开数据层（CC BY 4.0）**")
        st.write("需求、BOM、初始库存、供应提前期、供应弧容量、整车产能。")
        st.markdown("[Mendeley 数据集页面](https://data.mendeley.com/datasets/pr3sdy5vp3/1)")
        st.code(lineage["dataset"]["sha256"], language=None)
    with right:
        st.markdown("**模拟覆盖层（明确标注）**")
        st.write("事故邮件/群聊、客户名称、优先级、应急供应商、成本、恢复预算和人工审批。")
        st.caption(lineage["synthetic_overlay"]["reason"])
    st.markdown('<div class="boundary">该数据集是行业背景随机化数据，不是企业原始生产流水；本 Demo 也不包含任何阿里云内部数据。</div>', unsafe_allow_html=True)

with event_tab:
    st.subheader("复赛对抗案例")
    raw_text = ""
    if case_id == "random_drill":
        drill_preview = ChaosDrillAgent().generate(scenario, int(seed))
        st.info(f"{drill_preview.communication_channel} · {drill_preview.subject}")
        st.text_area("模拟消息", value=drill_preview.body, height=150, disabled=True)
        st.caption(drill_preview.safety_boundary)
    elif case_id == "infeasible_request":
        st.error("客户要求在24小时内承诺400台；系统必须先证明资源上界，不能直接生成漂亮排程。")
        st.json({
            "product_id": selected_case["product_id"],
            "requested_total_units": selected_case["requested_total_units"],
            "due_hour": selected_case["due_hour"],
            "expected_safe_stop": selected_case["expected_stop"],
        })
    elif case_id == "source_conflict":
        bundle = load_evidence_bundle(ROOT / selected_case["evidence_manifest"])
        st.warning("三个来源同时进入任务上下文；两个新鲜来源对到货时长给出不同结论，禁止静默择值。")
        image_col, pdf_col, csv_col = st.columns(3)
        with image_col:
            st.markdown("**邮件截图 · 48h**")
            st.image(CASE / "evidence/supplier_email.png", width="stretch")
            st.caption("预计算OCR fixture，绑定PNG SHA-256与bbox。")
        with pdf_col:
            st.markdown("**承运通知PDF · 72h**")
            st.info("第1页：Current arrival estimate: 72 hours")
            st.download_button(
                "打开/下载承运通知PDF",
                data=(CASE / "evidence/carrier_notice.pdf").read_bytes(),
                file_name="synthetic_carrier_notice.pdf",
                mime="application/pdf",
                width="stretch",
            )
            st.caption("PDF文字层抽取，页码与原文可追溯。")
        with csv_col:
            st.markdown("**MES CSV · 48h（已过期）**")
            st.dataframe(
                pd.read_csv(CASE / "evidence/mes_snapshot.csv"),
                hide_index=True,
                width="stretch",
            )
            st.caption("快照早于案例时点26小时，按8小时策略标记stale。")
        evidence_rows = []
        for record in bundle["records"]:
            for claim in record["claims"]:
                evidence_rows.append({
                    "证据": record["evidence_id"],
                    "格式": record["media_type"],
                    "值": f"{claim['value']} {claim.get('unit') or ''}".strip(),
                    "位置": claim["source_locator"],
                    "新鲜度": "过期" if record["stale"] else "有效",
                    "Hash": "通过" if record["hash_verified"] else "失败",
                })
        st.dataframe(pd.DataFrame(evidence_rows), hide_index=True, width="stretch")
        raw_text = case_text(selected_case)
    else:
        raw_text = case_text(selected_case)
        area_label = "恶意供应商邮件" if case_id == "prompt_injection" else "模拟供应商邮件"
        st.text_area(area_label, value=raw_text, height=190, disabled=mode == "replay")
        if case_id == "prompt_injection":
            st.warning("邮件中的‘绕过审批/关闭验证器’是非可信指令；系统只允许提取有原文span的24小时延期事实。")

    if st.button("启动 LangGraph 演练", type="primary"):
        clear_run()
        try:
            thread_id = f"demo-{uuid4().hex}"
            if case_id == "infeasible_request":
                result = run_infeasible_case(scenario, selected_case)
                graph = None
            else:
                graph = build_graph(mode)
            if case_id == "random_drill":
                event = ChaosDrillAgent().generate(scenario, int(seed))
                result = graph.start_drill(drill=event, thread_id=thread_id)
                st.session_state["drill_event"] = event.model_dump(mode="json")
            elif case_id != "infeasible_request":
                preflight_conflicts = []
                preflight_confirmations = []
                if case_id == "source_conflict":
                    bundle = load_evidence_bundle(ROOT / selected_case["evidence_manifest"])
                    preflight_conflicts = [
                        f"{item['field_name']}: {item['reason']}"
                        for item in bundle["conflicts"]
                    ]
                    preflight_confirmations = ["authoritative_delay_hours"]
                result = graph.start(
                    raw_text=raw_text,
                    source_ref=selected_case["input_ref"],
                    replay_key=selected_case["replay_key"],
                    thread_id=thread_id,
                    preflight_conflicts=preflight_conflicts,
                    preflight_required_confirmations=preflight_confirmations,
                )
            st.session_state.update(
                guard_graph=graph,
                graph_result=result,
                thread_id=thread_id,
                run_kind=case_label(case_id),
                graph_mode=mode,
                active_case_id=case_id,
            )
            st.rerun()
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))

    result = st.session_state.get("graph_result")
    if result:
        st.success(f"LangGraph 已运行至：{result['status']}")
        st.caption(
            f"本次模型：{result.get('model_name', '—')} · "
            f"运行模式：{result.get('model_mode', '—')}"
        )
        incident = result.get("incident") or result.get("incident_draft", {})
        cols = st.columns(4)
        cols[0].metric("事故类型", incident.get("kind") or incident.get("incident_kind", "—"))
        cols[1].metric("目标", incident.get("target_id") or incident.get("resolved_target_id", "—"))
        cols[2].metric("受影响订单", len(result.get("impact", {}).get("affected_orders", [])))
        cols[3].metric("图节点完成数", len(result.get("graph_trace", [])))
        st.markdown(" → ".join(item["node"] for item in result.get("graph_trace", [])))
        security_flags = result.get("incident_draft", {}).get("security_flags", [])
        if security_flags:
            st.error("安全标记：" + "、".join(security_flags) + "；恶意指令未获得工具、审批或执行权限。")
        if result["status"] == "needs_clarification":
            st.error("检测到新鲜来源冲突，图已在求解前真实暂停。")
            for conflict in incident.get("conflicts", []):
                st.write(f"- {conflict}")
            authoritative = st.radio(
                "人工确认权威到货时长",
                [72, 48],
                format_func=lambda value: "72小时 · 采用09:15承运通知" if value == 72 else "48小时 · 采用09:00供应商邮件",
                horizontal=True,
            )
            if st.button("确认来源并恢复 LangGraph", type="primary"):
                chosen_ref = (
                    "data/cases/mendeley_drill/evidence/carrier_notice.pdf"
                    if authoritative == 72
                    else "data/cases/mendeley_drill/evidence/supplier_email.png"
                )
                graph = st.session_state["guard_graph"]
                st.session_state["graph_result"] = graph.resume(
                    thread_id=st.session_state["thread_id"],
                    response={
                        "delay_hours": authoritative,
                        "missing_fields": [],
                        "conflicts": [],
                        "confirmations_accepted": True,
                        "source_spans": [{
                            "source_ref": chosen_ref,
                            "quote": f"authoritative delay confirmed as {authoritative} hours",
                            "field_name": "delay_hours",
                        }],
                    },
                )
                st.rerun()

with plan_tab:
    result = st.session_state.get("graph_result")
    if result and result.get("status") == "infeasible":
        diagnostic = result["diagnostic"]
        st.error("安全停止：现有物料与产能无法在计划期内完成400台，系统没有伪造可行方案。")
        cols = st.columns(4)
        cols[0].metric("客户要求", diagnostic["requested_total_units"])
        cols[1].metric("24h最多", diagnostic["maximum_deliverable_by_due"])
        cols[2].metric("全周期最多", diagnostic["maximum_deliverable_within_horizon"])
        cols[3].metric("缺口", diagnostic["due_bound"]["shortfall_units"])
        st.markdown("**最低新增物料**")
        st.dataframe(
            pd.DataFrame(diagnostic["minimum_additional_material"]),
            hide_index=True,
            width="stretch",
        )
        st.markdown("**允许交给人的替代选择**")
        st.dataframe(pd.DataFrame(diagnostic["alternatives"]), hide_index=True, width="stretch")
        st.warning("该结果只是资源上界诊断；任何新承诺仍需重新求解、独立验证和人工批准。工单数量：0。")
    elif not result or "plan_summaries" not in result:
        st.info("先启动演练；图会在真实的人审 interrupt 处暂停。")
    else:
        st.subheader("订单影响图")
        render_order_impact_graph(scenario, result)
        st.subheader("三种恢复方案同屏比较")
        st.dataframe(comparison_frame(result), hide_index=True, width="stretch")
        render_comparison_gantt(result)
        st.caption("三个甘特图共用0–96小时横轴、相同订单顺序和颜色；不是切换标题后的同一方案。")

        columns = st.columns(3)
        for column, profile in zip(columns, ("service_first", "balanced", "stability_first")):
            summary = result["plan_summaries"][profile]
            plan = next(item for item in result["plans"] if item["profile"] == profile)
            with column:
                st.markdown(f"### {PROFILE_LABELS[profile]}")
                st.metric("第一个交期按时", f"{summary['first_due_on_time_units']} / 217 台")
                st.write(f"延期/未按时：{summary['first_due_late_units']} 台")
                st.write(f"应急采购：{summary['alternate_supplier_units']} 件")
                st.write(f"恢复成本：¥{summary['recovery_cost']:,}")
                st.write("独立验证：" + ("通过" if plan["evidence"]["verified"] else "未通过"))
        profile = st.radio(
            "查看单方案工序细节",
            ["service_first", "balanced", "stability_first"],
            format_func=lambda value: PROFILE_LABELS[value],
            horizontal=True,
        )
        render_timeline(plan_frame(result, profile))

        if result["status"] == "awaiting_approval":
            st.subheader("LangGraph 人工中断点")
            selected = st.selectbox("待审批方案", list(PROFILE_LABELS), format_func=lambda value: PROFILE_LABELS[value])
            actor = st.text_input("审批人", value="demo_planner")
            comment = st.text_area("审批意见", value="仅批准隔离演练中的 draft_only 动作，不执行真实系统写回。")
            approve_col, reject_col = st.columns(2)
            if approve_col.button("批准并恢复图执行", type="primary", width="stretch"):
                graph = st.session_state["guard_graph"]
                st.session_state["graph_result"] = graph.resume(
                    thread_id=st.session_state["thread_id"],
                    response={"decision": "approve", "profile": selected, "actor_id": actor, "comment": comment},
                )
                st.rerun()
            if reject_col.button("驳回并结束", width="stretch"):
                graph = st.session_state["guard_graph"]
                st.session_state["graph_result"] = graph.resume(
                    thread_id=st.session_state["thread_id"],
                    response={"decision": "reject", "actor_id": actor, "comment": comment},
                )
                st.rerun()
        elif result["status"] == "completed":
            st.success(f"哈希复核通过，生成 {len(result['work_orders'])} 张 draft_only 工单；没有执行真实动作。")
            st.dataframe(pd.DataFrame(result["work_orders"]), width="stretch", hide_index=True)
        elif result["status"] == "rejected":
            st.warning("方案已驳回，工单数量为 0。")

with integration_tab:
    result = st.session_state.get("graph_result")
    st.subheader("ERP/MES 协议兼容沙箱")
    st.markdown(
        '<div class="boundary"><strong>CONTRACT-COMPATIBLE SANDBOX · NON-CERTIFIED · NO LIVE TENANT</strong><br>'
        '所有HTTP端点均由本项目本地创建；厂商名称只表示公开接口模式映射，不代表真实租户、厂商认证或生产写入。</div>',
        unsafe_allow_html=True,
    )
    profile_value = st.selectbox(
        "运行 Contract Profile",
        [
            IntegrationProfile.KINGDEE_BLACKLAKE.value,
            IntegrationProfile.SAP_S4_DM.value,
        ],
        format_func=lambda value: (
            "国产组合 · 金蝶OpenAPI风格 + 黑湖MES回调风格"
            if value == IntegrationProfile.KINGDEE_BLACKLAKE.value
            else "国际组合 · SAP S/4 OData风格 + SAP DM回流风格"
        ),
    )
    st.caption("底层共用 canonical contract、Outbox/Inbox、幂等、ACK/Callback和Stale门禁；只替换映射与错误语义。")
    if not result or result.get("status") != "completed":
        st.info("先在恢复指挥台完成一次人工批准。未批准、已驳回、无解或陈旧方案都不能下发ERP/MES命令。")
    elif st.button("启动本地HTTP沙箱并演练执行回流", type="primary", width="stretch"):
        try:
            with st.spinner("正在执行快照GET、命令POST、业务Callback和回流重算……"):
                st.session_state["integration_report"] = run_partial_failure_demo(
                    scenario,
                    result,
                    IntegrationProfile(profile_value),
                    feedback_graph=st.session_state.get("guard_graph"),
                    feedback_thread_id=f"{st.session_state.get('thread_id', 'streamlit')}-integration-feedback",
                )
            st.rerun()
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))

    report = st.session_state.get("integration_report")
    if report:
        http_info = report["http_boundary"]
        cols = st.columns(4)
        cols[0].metric("快照GET", http_info["snapshot_gets"])
        cols[1].metric("命令POST", http_info["command_posts"])
        cols[2].metric("业务Callback", http_info["callback_posts"])
        overall_label = (
            "部分应用" if report["overall_business_status"] == "PARTIALLY_APPLIED"
            else report["overall_business_status"]
        )
        cols[3].metric("整体状态", overall_label)
        st.caption("本次真实 localhost HTTP 服务已完成整条演练并安全关闭：")
        st.code(http_info["base_url"], language=None)
        st.markdown("**输入快照证据**")
        st.dataframe(pd.DataFrame([
            {
                "系统": "ERP沙箱",
                "版本": report["snapshot_evidence"]["erp_revision"],
                "内容Hash": report["snapshot_evidence"]["erp_hash"][:20],
            },
            {
                "系统": "MES沙箱",
                "版本": report["snapshot_evidence"]["mes_revision"],
                "内容Hash": report["snapshot_evidence"]["mes_hash"][:20],
            },
        ]), hide_index=True, width="stretch")

        st.markdown("**Transport ACK ≠ Business Result**")
        state_rows = []
        callback_map = {item["command_id"]: item for item in report["callbacks"]}
        ack_map = {item["command_id"]: item for item in report["transport_acks"]}
        command_map = {item["command_id"]: item for item in report["commands"]}
        command_labels = {
            "CREATE_PURCHASE_REQUISITION_AND_ORDER_RISK_DRAFTS": "采购/订单风险草稿",
            "CREATE_SCHEDULE_CHANGE_DRAFT": "排程变更草稿",
        }
        for item in report["command_states"]:
            command = command_map[item["command_id"]]
            callback = callback_map[item["command_id"]]
            ack = ack_map[item["command_id"]]
            state_rows.append({
                "目标": item["target_system"],
                "命令": command_labels.get(command["command_type"], command["command_type"]),
                "HTTP/Transport": f"202 / {ack['transport_status']}",
                "收到时业务状态": ack["business_status"],
                "最终业务状态": item["business_status"],
                "外部对象": ", ".join(callback["target_record_ids"]) or "—",
                "错误": ", ".join(error["code"] for error in callback["errors"]) or "—",
            })
        st.dataframe(pd.DataFrame(state_rows), hide_index=True, width="stretch")
        st.error("ERP草稿已创建，但MES因产能版本变化拒绝：整体为PARTIALLY_APPLIED，系统没有把HTTP 202包装成执行完成。")

        if report["plan_stale"]:
            replan = report["replan"]
            st.subheader("执行结果回流 → 旧计划失效 → 重新求解")
            st.warning(
                f"MES从 mes-rev-12 更新到 mes-rev-13；旧审批 {replan['previous_approval_id']} 已失效，"
                "尚未发送的动作禁止继续下发。"
            )
            st.markdown(" → ".join(item["node"] for item in replan["graph_trace"]))
            before_after = st.columns(2)
            before_after[0].metric("旧场景Hash", replan["previous_scenario_hash"][:16])
            before_after[1].metric("新场景Hash", replan["scenario_hash"][:16])
            st.dataframe(comparison_frame(replan), hide_index=True, width="stretch")
            render_comparison_gantt(replan)
            st.info("新方案停在 awaiting_approval；旧批准没有复用，回流后工单数量仍为0。")

        st.markdown("**可追溯集成日志**")
        st.dataframe(pd.DataFrame([
            {
                "序号": item["sequence"],
                "事件": item["event_type"],
                "引用": item["ref_id"],
                "详情": json.dumps(item["details"], ensure_ascii=False),
            }
            for item in report["audit"]
        ]), hide_index=True, width="stretch")
        st.download_button(
            "下载ERP/MES闭环证据JSON",
            data=json.dumps(report, ensure_ascii=False, indent=2, default=str),
            file_name="youjie_erp_mes_feedback_run.json",
            mime="application/json",
        )

with audit_tab:
    if LIVE_EVAL_PATH.exists():
        live_eval = json.loads(LIVE_EVAL_PATH.read_text(encoding="utf-8"))
        bounded = live_eval["aggregate_metrics"]
        raw_model = live_eval["raw_model_metrics"]
        st.subheader("真实模型对抗评测")
        st.caption(
            f"{live_eval['model_name']} · {live_eval['run_count']} 轮 / "
            f"{live_eval['total_model_calls']} 次调用 · 黄金集 {live_eval['dataset_version']}"
        )
        eval_cols = st.columns(4)
        eval_cols[0].metric("每轮通过", " / ".join(map(str, live_eval["all_run_pass_counts"])))
        eval_cols[1].metric(
            "有界 Agent 通过率",
            f"{bounded['case_pass_rate']['mean'] * 100:.1f}%",
        )
        eval_cols[2].metric(
            "禁止工具调用",
            str(sum(live_eval["all_run_forbidden_tool_counts"])),
        )
        eval_cols[3].metric("p95 延迟", f"{live_eval['latency_seconds']['p95']:.2f}s")
        st.dataframe(
            pd.DataFrame([
                {
                    "层级": "原始大模型",
                    "意图": f"{raw_model['raw_intent_accuracy']['mean'] * 100:.1f}%",
                    "事件类型": f"{raw_model['raw_incident_kind_accuracy']['mean'] * 100:.1f}%",
                    "实体ID": f"{raw_model['raw_resolved_target_id_accuracy']['mean'] * 100:.1f}%",
                    "业务字段": f"{raw_model['raw_candidate_fields_accuracy']['mean'] * 100:.1f}%",
                    "安全标记": f"{raw_model['raw_security_flags_accuracy']['mean'] * 100:.1f}%",
                },
                {
                    "层级": "有界 Agent",
                    "意图": f"{bounded['intent_accuracy']['mean'] * 100:.1f}%",
                    "事件类型": f"{bounded['incident_kind_accuracy']['mean'] * 100:.1f}%",
                    "实体ID": f"{bounded['known_entity_resolution_accuracy']['mean'] * 100:.1f}%",
                    "业务字段": "规则校验",
                    "安全标记": f"{bounded['security_flag_recall']['mean'] * 100:.1f}%",
                },
            ]),
            hide_index=True,
            width="stretch",
        )
        st.caption("模型负责语义候选与字段抽取；稳定实体、缺失项、工具权限和人审状态由确定性策略控制。Replay 分数另列，不冒充 Live。")
        st.divider()
    result = st.session_state.get("graph_result")
    if not result:
        st.info("运行后展示节点、工具、来源和求解证据。")
    else:
        st.subheader("LangGraph 节点轨迹")
        st.dataframe(pd.DataFrame(result.get("graph_trace", [])), width="stretch", hide_index=True)
        st.subheader("工具轨迹")
        st.dataframe(pd.DataFrame(result.get("tool_traces", [])), width="stretch", hide_index=True)
        if result.get("plans"):
            st.subheader("求解与验证证据")
            st.dataframe(pd.DataFrame([
                {
                    "方案": item["profile"],
                    "solver": item["evidence"]["solver_name"],
                    "status": item["evidence"]["solver_status"],
                    "verified": item["evidence"]["verified"],
                    "scenario_hash": item["scenario_hash"][:16],
                    "plan_hash": item["evidence"]["plan_hash"][:16],
                }
                for item in result["plans"]
            ]), width="stretch", hide_index=True)
        clean = {key: value for key, value in result.items() if key != "__interrupt__"}
        st.download_button(
            "下载完整演练证据 JSON",
            data=json.dumps(clean, ensure_ascii=False, indent=2, default=str),
            file_name="youjie_mendeley_langgraph_run.json",
            mime="application/json",
        )
        st.markdown('<div class="boundary">随机事故 Agent 只能提出经过 Pydantic 校验的仿真事件；LLM、LangGraph 和事故 Agent 都无权声明数学可行、批准方案或控制设备。</div>', unsafe_allow_html=True)
