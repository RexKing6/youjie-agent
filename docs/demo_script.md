# 5 分钟演示脚本

## 0:00–0:45：先证明数据

打开“公开数据证据”。台词：

“这次不是只参考 schema。项目包含 Mendeley CC BY 4.0 原始 `.xlsb`，启动前校验完整文件 SHA-256。我们从第 61 期选择三个重复 BOM 配置，共 217 条逐车需求；聚合后仍为 217 台，数量差为 0。点开 `lineage.json` 可以回到每一条 `demands`、BOM、库存和容量行。”

明确说明：公开数据是行业背景随机化数据；客户、事故、报价和审批是模拟层。

## 0:45–1:35：输入事故并展示 LangGraph

选择“固定供应商邮件”，Replay 模式，点击“启动 LangGraph 演练”。

展示事故：Q2J seat supply 延迟 48 小时，三张订单全部受影响。指出节点轨迹：

`understand_incident → plan_investigation → execute_investigation → analyze_and_solve`

页面停在 `awaiting_approval`，这是 LangGraph 的真实 `interrupt`，不是按钮模拟状态。

台词：“LLM 只把邮件变成带 source span 的候选事故；LangGraph 选择白名单工具；BOM、库存、产能和可行性由确定性代码计算。”

## 1:35–2:40：三方案真实差异

- 保交付：91 / 217 按时，应急 91 件，恢复成本 ¥728。
- 平衡：45 / 217 按时，应急 45 件，恢复成本 ¥360。
- 少变更：0 / 217 按时，应急 0 件，恢复成本 ¥0。

三份方案均为 `OPTIMAL` 并通过独立 verifier。切换排程图，指出订单、开始/结束小时和产线。

解释为什么保交付不是 217 全准时：模拟应急来源只有 100 件，三张订单又必须整批交付；91 台关键订单是预算和供给下能保住的最大完整订单。系统不会拆掉 `must_ship_complete` 来制造漂亮数字。

## 2:40–3:30：真实人审中断与双 hash

选择“平衡方案”，填写意见，点击“批准并恢复图执行”。

展示 5 张 `draft_only` 工单。台词：

“恢复时不是直接沿用旧对象。系统重新求解和验证，再核对 scenario hash 与 plan hash。只有审批看到的方案仍完全一致才生成草稿；它们不会被发送到真实系统。”

也可重新开始并选择“驳回”，证明工单为 0。

## 3:30–4:25：随机事故演练

切到“随机事故演练”，输入 seed。连续五个 seed 会覆盖供应延期、供应中断、库存损失、产线停机和需求激增。

点击启动，展示生成的 email/chat/MES 文案和结构化 Incident，再走同一 LangGraph、solver、verifier、人审链路。

台词：“随机 Agent 不是另一个会拍脑袋的聊天角色。它只能从现有 ID 和合法范围生成事故，无权批准或执行。相同 seed 完全可复现。”

## 4:25–5:00：审计与收束

打开“工具审计”，展示：

- 图节点轨迹；
- snapshot / policy retrieval / impact / solver 工具记录；
- OR-Tools 版本、solver status、verified、scenario hash、plan hash；
- 可下载的完整 JSON。

收束：

“成熟 ERP/APS 已经会管订单和排程。有界的差异不是再造 CRUD，而是把非结构化异常、公开数据证据、联合求解、独立验证、耐久人审和安全动作门禁放进一个可复现闭环。”

## 演示前检查

```bash
.venv/bin/python scripts/build_mendeley_case.py
.venv/bin/python -m pytest -q
.venv/bin/python -m delivery_guard.cli run-graph --case-dir data/cases/mendeley_drill --replay data/model_replays/mendeley_drill.json --output artifacts/public_data_graph_run.json
.venv/bin/python -m delivery_guard.cli run-drill --case-dir data/cases/mendeley_drill --replay data/model_replays/mendeley_drill.json --seed 20260810 --output artifacts/chaos_drill_run.json
.venv/bin/python scripts/verify_artifacts.py
.venv/bin/streamlit run app.py --server.headless true
```
