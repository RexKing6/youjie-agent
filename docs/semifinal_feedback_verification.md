# 复赛意见与规则逐项反审

> 反审日期：2026-08-29。状态只以仓库中可复算证据为准，不以 PPT 文案为准。

## 结论

初赛评审的两条定向意见都已落到可运行产品链路：三方案同轴甘特图与订单影响图已进入“恢复驾驶舱”；真实 ERPNext v16 本机测试实例已完成认证 REST、主数据、4 张新增草稿写入/回读、既有 committed 供应防重复、限定单据回流、revision 与幂等验证；真实 OpenMES 本机测试实例通过官方 ERP API 接收 ERPNext 同号工单、回读应用层执行状态，并在人工状态变化后使旧批准失效。商业系统的异步回调与部分失败仍由合同沙箱验证。必须区分“真实开源测试实例”和“协议兼容沙箱”，不能说已接入 SAP、金蝶或黑湖生产系统。

## 一、定向评审意见

| 原始意见 | 实现 | 如何验证 | 自动验证 | 状态 |
|---|---|---|---|---|
| 用甘特图比较交付数量、恢复成本、资源调整 | 三个 solver-verified 方案使用同一 0–96h 时间轴；同时显示按时量、延迟量、成本、应急采购和加班 | Demo“恢复驾驶舱”三方案对比与甘特图 | `tests/test_solver.py`、`tests/test_integration_contracts.py`；方案证据仍由独立 verifier 校验 | 完成 |
| 用订单影响图呈现异常传播 | supplier→material→product→order→line 有向关系图，节点来自当前场景/影响结果，不是静态图片 | Demo“恢复驾驶舱”顶部影响图 | 现有 impact/graph 测试验证受影响对象；浏览器人工检查布局 | 完成 |
| 增加在线模型运行 | Live 与 Replay 明确分离；真实 `qwen3.8-max` 已完成 3×30=90 次调用及四个主案例 | Live 审计页、`artifacts/live_agent_eval_report.json`、`live_semifinal_report.json` | `scripts/verify_artifacts.py` 核验调用轮数、结果和密钥未进入报告 | 完成，有边界 |
| 增加多轮稳定性测试 | 四种集成 profile 各 10 次完整 HTTP 链路；剔除临时端口和求解耗时后业务结果 digest 一致；真实 ERPNext/OpenMES 实例另列 | `artifacts/integration_validation_report.json` | `scripts/run_integration_validation.py --runs 10`，当前 72/72 | 完成 |
| 展示 ERP/MES 对接 | 真实 ERPNext REST + 真实 OpenMES ERP API + canonical snapshots、OpenAPI/AsyncAPI、JSON Schema、outbox/inbox、两种商业系统合同 profile | Live Workbench 的 ERPNext/OpenMES 同号记录；Demo“ERP→MES回流”；`contracts/` | `erpnext_real_validation.json`、`openmes_real_validation.json`、schema 解析、HTTP 测试、profile 重跑 | 两个开源测试实例完成；商业系统仍为沙箱 |
| 展示执行结果回流 | HTTP 202 后仍 PENDING；ERP APPLIED、MES REJECTED→PARTIALLY_APPLIED→产能变更→旧批准失效→重算等待新审批 | Demo“ERP/MES回流”完整链路 | ADV-05/06/09/10/11/14/15/16 | 完成 |

## 二、复赛提交硬性要求

| 规则 | 仓库证据 | 验证方法 | 状态/剩余动作 |
|---|---|---|---|
| 更新版 PPT/PDF | `docs/youjie_goai_semifinal_pitch_8slides.pptx/.pdf` | 8 页主线已包含三方案可视化、真实工作台、ERPNext→OpenMES 与验证证据；PPT/PDF 均逐页检查 | **完成** |
| 至少一条完整链路 | 输入→LLM→LangGraph工具→CP-SAT/verifier→人审→草稿→ERP/MES回流→异常重算 | 现场走主链路；视频备用 | 完成 |
| 在线、本地或视频可验证 Demo | Streamlit 本地入口；Replay 无 key 可跑；Live 需运行时 secret | 按 README 新环境安装运行；视频断网兜底 | 完成，公开网址非硬要求 |
| 展示异常处理 | 来源冲突暂停、全局无解、提示注入、ERP/MES部分失败、乱序/重复回调 | 四个 UI 案例 + `integration_validation_report.json` | 完成 |
| 代码和工程材料 | 入口、依赖、配置说明、样例数据、测试、运行证据 | 解压 ZIP 后按 README 运行；`verify_artifacts.py` | 完成，需最终重打包 |
| 数据来源和授权 | Mendeley 原文件、DOI、CC BY 4.0、SHA-256、lineage；模拟覆盖层分开 | `data_provenance.md`、`lineage.json`、`THIRD_PARTY_NOTICES.md` | 完成 |
| 隐私与脱敏 | 不含真实个人/企业/阿里云内部数据；密钥不打包 | ZIP 自动扫描 `.env`/`secrets.toml`/`erpnext_credentials.json` | 完成 |
| 工业风险边界 | L3/L4 事务草稿与反馈；禁止设备控制；不替代现场判断 | schema ADV-13、UI disclosure、README | 完成 |
| 开放/复用 | Apache-2.0、canonical contract、双 profile、示例、测试 | `LICENSE`、`contracts/`、`src/delivery_guard/integration/` | 完成 |

## 三、按评审权重反审

| 维度 | 已有强证据 | 仍会被追问的弱点 | 答辩策略 |
|---|---|---|---|
| 行业价值 25% | 制造计划员、217 台订单、供应延迟与产能冲突、三方案量化权衡 | 未用真实企业历史事故，不能证明节省金额/时间 | 主动说 PoC 证明机制；下一步用授权脱敏历史 replay 做 A/B |
| Agent 闭环 25% | 多格式输入、LLM、LangGraph规划/工具/记忆、双 interrupt、回流再规划 | “Agent 是否只是工作流” | 展示模型负责非结构化理解和动态调查，确定性内核负责高风险数值；两者缺一不可 |
| 产品/Demo 20% | 影响图、甘特对比、错误提示、完整异常链路 | 页面信息密度高、现场时间有限 | 只走一条主线；预置结果和视频兜底，不现场等 90 次调用 |
| 技术深度 15% | LangGraph、CP-SAT、verifier、hash、人审、真实 ERPNext REST、真实 OpenMES ERP API、HTTP/outbox/inbox、schema | 两个真实系统仍是本机测试实例 | 展示跨系统同号记录、GET 回读、revision 与旧批准失效；同时明确生产授权与 adapter 差距 |
| 安全合规 10% | 数据 lineage、prompt injection、禁止设备写、审批失效、密钥扫描 | 本地 InMemorySaver/SQLite 不适合生产高可用 | 承认 PoC；生产化列出持久化、RBAC、mTLS、审计签名 |
| 开放复用 5% | 代码、数据派生、合同、测试、证据报告 | 尚未形成第三方采用数据 | 展示任何 ERP/MES 只需替换 adapter 的最小接口面 |

## 四、最终验收命令

```bash
PYTHONPATH=src .venv/bin/python scripts/run_integration_validation.py --runs 10
PYTHONPATH=src .venv/bin/python scripts/export_integration_contracts.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/package_submission.py
.venv/bin/python scripts/verify_artifacts.py
.venv/bin/python -m compileall -q src app.py scripts tests
```

若任一命令失败，材料不能标记为“复赛可提交”。
