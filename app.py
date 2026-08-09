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
from delivery_guard.graph import DeliveryGuardGraph
from delivery_guard.llm import OpenAICompatibleLanguageModel, ReplayLanguageModel


ROOT = Path(__file__).resolve().parent
CASE = ROOT / "data/cases/mendeley_drill"
RAW = ROOT / "data/public/mendeley_automotive/2020_dataset_automotive_production_network.xlsb"
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
    for key in ("guard_graph", "graph_result", "thread_id", "drill_event", "run_kind", "graph_mode"):
        st.session_state.pop(key, None)


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
    mode = st.radio(
        "语言模型",
        ["replay", "live"] if LIVE_LLM_AVAILABLE else ["replay"],
        format_func=lambda value: "离线 Replay" if value == "replay" else "Live OpenAI-compatible",
    )
    if not LIVE_LLM_AVAILABLE:
        st.caption("公开版未配置模型密钥，因此仅开放可复现 Replay；密钥不会由页面采集。")
    run_kind = st.radio("事件来源", ["固定供应商邮件", "随机事故演练"])
    seed = st.number_input("演练 seed", min_value=0, max_value=99_999_999, value=20260810, step=1)
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

lineage = json.loads((CASE / "lineage.json").read_text(encoding="utf-8"))
scenario = load_scenario(CASE / "scenario.json")
data_tab, event_tab, plan_tab, audit_tab = st.tabs(
    ["① 公开数据证据", "② 事故与 Agent", "③ 方案与人审", "④ 工具审计"]
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
    st.subheader("输入事件")
    if run_kind == "固定供应商邮件":
        raw_text = (CASE / "supplier_delay_email.txt").read_text(encoding="utf-8")
        st.text_area("模拟邮件", value=raw_text, height=190, disabled=mode == "replay")
    else:
        drill_preview = ChaosDrillAgent().generate(scenario, int(seed))
        st.info(f"{drill_preview.communication_channel} · {drill_preview.subject}")
        st.text_area("模拟消息", value=drill_preview.body, height=150, disabled=True)
        st.caption(drill_preview.safety_boundary)

    if st.button("启动 LangGraph 演练", type="primary"):
        clear_run()
        try:
            graph = build_graph(mode)
            thread_id = f"demo-{uuid4().hex}"
            if run_kind == "固定供应商邮件":
                result = graph.start(
                    raw_text=raw_text,
                    source_ref="data/cases/mendeley_drill/supplier_delay_email.txt",
                    replay_key="mendeley_seat_delay_email",
                    thread_id=thread_id,
                )
            else:
                event = ChaosDrillAgent().generate(scenario, int(seed))
                result = graph.start_drill(drill=event, thread_id=thread_id)
                st.session_state["drill_event"] = event.model_dump(mode="json")
            st.session_state.update(
                guard_graph=graph,
                graph_result=result,
                thread_id=thread_id,
                run_kind=run_kind,
                graph_mode=mode,
            )
            st.rerun()
        except RuntimeError as exc:
            st.error(str(exc))

    result = st.session_state.get("graph_result")
    if result:
        st.success(f"LangGraph 已运行至：{result['status']}")
        incident = result.get("incident", {})
        cols = st.columns(4)
        cols[0].metric("事故类型", incident.get("kind", "—"))
        cols[1].metric("目标", incident.get("target_id", "—"))
        cols[2].metric("受影响订单", len(result.get("impact", {}).get("affected_orders", [])))
        cols[3].metric("图节点完成数", len(result.get("graph_trace", [])))
        st.markdown(" → ".join(item["node"] for item in result.get("graph_trace", [])))

with plan_tab:
    result = st.session_state.get("graph_result")
    if not result or "plan_summaries" not in result:
        st.info("先启动演练；图会在真实的人审 interrupt 处暂停。")
    else:
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
            "查看排程",
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

with audit_tab:
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
