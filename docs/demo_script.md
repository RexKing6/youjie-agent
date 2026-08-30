# 5 分钟复赛演示脚本（复赛版）

## 0:00-0:35：先把边界说清楚

打开“公开数据证据”。

“基础需求、BOM、库存和供应网络来自 Mendeley CC BY 4.0 原始 `.xlsb`；文件先做 SHA-256 校验，217 条逐车需求聚合后仍是 217 台。事故邮件、客户、价格、预算和审批是明确标注的确定性模拟。本系统不含企业内部数据；ERPNext 与 OpenMES 是真实本机开源测试实例，SAP/金蝶/黑湖部分是项目自建协议兼容沙箱；都不是生产系统，也不控制设备。”

## 0:35-1:25：多格式证据冲突必须真实暂停

选择“来源冲突：邮件48h vs 承运通知72h”，打开“事故与 Agent”。依次指出：

- PNG 邮件截图：48h，OCR fixture 绑定图片 hash 和 bbox；
- PDF 承运通知：第 1 页明确写 72h；
- MES CSV：48h，但早于案例时点 26 小时，超过 8 小时新鲜度窗口。

点击“启动 LangGraph 演练”。

“两个新鲜来源冲突时，系统没有静默选择一个数字，也没有进入求解。图在 `understand_incident` 后停到 `needs_clarification`。这是真正的状态中断。”

保持默认“72小时 · 采用09:15承运通知”，点击“确认来源并恢复 LangGraph”。展示 `clarify_incident → plan_investigation → execute_investigation → analyze_and_solve`，以及 `awaiting_approval`。

## 1:25-2:35：影响图、三方案甘特和人审门

打开“恢复驾驶舱”，先指 supplier→material→product→order→line 影响图，再指同一时间轴上的三张甘特图：

- 保交付：91 / 217 按时，应急 91，成本 ¥728；
- 平衡：45 / 217 按时，应急 45，成本 ¥360；
- 少变更：0 / 217 按时，应急 0，成本 ¥0。

“这不是三段文字换标题。每个方案同时展示交付量、延迟量、成本、应急采购、加班和产线资源调整。三个方案共用硬约束并经过独立 verifier。LLM 不计算可行性；CP-SAT 产出候选，verifier 从输出 JSON 重放硬约束。批准后还会重算并核对 scenario hash 和 plan hash，只生成 `draft_only` 工单。”

批准“平衡”方案，先写入真实 ERPNext 测试实例，再把三张生产工单用同一编号下发到真实 OpenMES，最后展示商业系统合同沙箱的部分失败语义。

## 2:35-3:15：真实 ERPNext 草稿写入与回读

选择 `erpnext_open_source_test_profile`：

1. 页面显示已认证测试实例，但不返回 API key；
2. 人审后实际创建 1 张应急 Material Request 与 3 张 Work Order 草稿；原有 217 件 committed 供应只引用、不重复建单；
3. 展示 ERPNext 返回的真实记录 ID、`docstatus=0`、GET 回读证据 hash；
4. 写前/写后 revision 改变；重复执行由幂等 ledger 拦截，不新增记录；
5. 强调提交、报工、Job Card 和设备动作仍由人或业务系统完成。

## 3:15-4:25：独立 ERP/MES 结果回流和失效重算

在 ERPNext 证据区点击“同步到真实 OpenMES”：

1. 展示三张 ERPNext Work Order 与 OpenMES `order_no` 一一对应；
2. OpenMES 初始状态为 `PENDING`，已产量为 `0`；
3. 打开 OpenMES，由人对任一工单执行“接单”；
4. 返回有界点击“读取真实 MES 回流”，状态变化、revision 变化，旧 approval 失效，新命令被阻断；
5. 明确这是应用层执行状态，不是物理设备执行。

随后选择 `kingdee_blacklake_contract_profile`，运行合同沙箱：

1. ERP 与 MES 快照分别显示 source revision 和 content hash；
2. 两个 command 都绑定 approval/scenario/plan hash，进入 outbox；
3. HTTP 202 后业务状态仍是 `PENDING`；
4. ERP callback 为 `APPLIED`，MES callback 因 capacity revision 为 `REJECTED`；
5. 整体明确显示 `PARTIALLY_APPLIED`，不假装事务全成功；
6. MES 回流使旧 scenario/plan 失效，重新求解后回到 `awaiting_approval`，新工单为 0。

“这是本机真实 HTTP/JSON、SQLite outbox/inbox 和异步 callback，但仍是合同兼容沙箱，不冒充 SAP、金蝶或黑湖真实租户。真实厂商接入只替换 adapter 的认证、字段映射和错误码；审批、幂等、失效重算和安全边界保持不变。”

## 4:10-4:35：正确答案可以是无解（备用追问页）

选择“全局无解：24小时承诺400台”，启动后进入“方案与人审”。

“客户要求 400 台，24 小时物料与产能共同上界是 305 台，缺口 95 台。系统返回 `infeasible`，列出最低新增物料与可讨论的替代选择，工单数量为 0。这里的正确答案不是一张漂亮排程，而是有数字依据地拒绝虚假承诺。”

## 4:35-4:50：提示注入没有执行权限（备用追问页）

选择“提示注入：邮件要求绕过审批”。指出邮件中同时存在：

- 恶意指令：忽略规则、关闭 verifier、立即采购；
- 可用业务事实：供应延迟 24 小时。

启动后展示 `prompt_injection` 安全标记和 `awaiting_approval`。

“模型只能提出候选字段和安全标记。恶意文本不能新增工具、伪造审批或修改 verifier。我们现在驳回。”

点击“驳回并结束”，证明工单为 0。

## 4:50-5:00：复算证据和收束

打开“工具审计”或直接展示附件：

- 完整 pytest；
- 15/15 求解与状态机对抗；
- 30/30 版本化 Replay 合同，禁止工具调用 0；
- `qwen3.8-max` 三轮 30/30，共 90 次真实调用，禁止工具调用 0，p95 2.69 秒；
- 12 个冻结案例的三系统架构对比：0/12、2/12、12/12，重复两次一致。
- 真实 ERPNext 4 张新增草稿写入/回读、committed 供应防重复、限定单据回流、revision 与幂等断言全部通过；真实 OpenMES 完成同号工单导入/回读与人工状态变化回流；四种集成 profile 各 10 次完整 HTTP 链路，当前 72/72 对抗检查通过。

“后一个比较只代表仓库内冻结参考实现，不是外部产品排名。有界的差异不是再造 ERP/APS，而是在其上方增加一个能够理解非结构化异常、调用工具、证明方案、遇到冲突和无解会停、最终把责任交还给人的决策层。”

补一句指标边界：“原始模型实体 ID 只有 40%，但业务字段 95.6%、安全标记 100%；稳定 ID、缺失项和工具权限由规则层接管，所以最终 Agent 不是靠大模型猜工业状态。”

## 演示前检查

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/build_multiformat_evidence.py
PYTHONPATH=src .venv/bin/python scripts/run_semifinal_comparison.py
PYTHONPATH=src .venv/bin/python scripts/run_integration_validation.py --runs 10
.venv/bin/python -m delivery_guard.cli run-graph --case-dir data/cases/mendeley_drill --replay data/model_replays/mendeley_drill.json --output artifacts/public_data_graph_run.json
.venv/bin/python scripts/verify_artifacts.py
.venv/bin/streamlit run app.py --server.headless true --server.port 8502
```
