# 答辩证据索引

评委不需要相信口头描述；每个主张都对应 UI、源文件和机器可读证据。

| 主张 | 现场入口 | 机器证据 | 源码/合同 | 断网兜底 |
|---|---|---|---|---|
| 公开汽车供应链原始行真实使用 | 数据证据页 | `data/cases/mendeley_drill/lineage.json` | `src/delivery_guard/mendeley.py` | PPT 数据页、视频 |
| 217→217 数量守恒 | 数据证据页 | lineage integrity | build script + test | 截图/PPT |
| 模型真实调用，不把 Replay 冒充 Live | Live 审计页 | `artifacts/live_agent_eval_report.json` | `src/delivery_guard/llm.py` | 90 次已生成报告 |
| 来源冲突会暂停 | 事故页选择冲突案例 | `artifacts/live_semifinal_report.json` | LangGraph clarify interrupt | 视频 |
| 三方案有真实量化差异 | 恢复驾驶舱 | `public_data_graph_run.json` | solver + verifier | PPT/JSON |
| 影响传播可解释 | 恢复驾驶舱影响图 | graph impact object | `impact.py` | PPT截图 |
| 批准前没有工单 | 人审节点 | integration ADV-01/02 | graph/workflow gate | JSON |
| HTTP 202 不等于执行成功 | ERP/MES 回流页 | ADV-05 | TransportAck/BusinessStatus schema | JSON/PPT |
| ERP成功、MES失败被标为部分应用 | ERP/MES 回流页 | ADV-06 | orchestrator + ledger | 视频/JSON |
| MES反馈使旧批准失效并重算 | ERP/MES 回流页 | ADV-09/10 | `replan_after_capacity_feedback` | 视频/JSON |
| 重复/乱序不造成二次副作用或状态倒退 | 不必现场操作 | ADV-03/04/07/08 | outbox/inbox ledger | JSON |
| 不控制设备 | 所有页面 disclosure | ADV-13 | CanonicalCommand validator | README/PPT |
| 双厂商组合只是合同 profile | ERP/MES profile 选择器 | 两 profile 各 10 次报告 | `contracts/` | mapping 文档 |
| 真实 ERPNext 不是口头宣称 | Live Workbench 真实记录 ID | 4 张新增草稿、1 条既有供应引用、GET 回读、限定范围 revision、幂等 | `artifacts/erpnext_real_validation.json` | JSON/现场 |
| 无解时不编排假方案 | 无解案例 | `infeasible_diagnostic.json` | diagnostics/solver | 视频 |
| 提示注入不能越权 | 注入案例 | comparison/live reports | schema + allowlist + gate | 视频 |

## 现场最小证据包

1. `docs/youjie_goai_semifinal_pitch.pdf`：答辩主材料。
2. `docs/youjie_semifinal_demo.mp4`：浏览器或网络故障时直接播放。
3. `artifacts/integration_validation_report.json`：当前 72/72 和四种集成 profile 各 10 次稳定性。
4. `artifacts/openmes_real_validation.json`：真实本机 ERPNext→OpenMES 三张同号工单、幂等回读、人工接单回流及旧审批失效证据。
4. `artifacts/live_agent_eval_report.json`：90 次真实模型调用。
5. `artifacts/youjie_semifinal_submission.zip`：评委复现代码包。
6. `contracts/openapi.yaml`：ERP/MES 对接不是一句概念文案的证明。
