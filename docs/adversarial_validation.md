# 对抗性验证报告

## 结果

- 自动化测试：27 passed。
- 对抗套件：15/15 passed，0 failed，0 invariant violations。
- Agent 评测：30/30 版本化 replay 合同通过，两次输出完全一致，0 次 forbidden tool。
- 主案例：3 个方案通过 CP-SAT 与独立验证；平衡方案批准后 16 张草稿动作。
- 两个不可行场景：0 个可批准方案；审批与工单被阻断。

权威机器可读结果在 `artifacts/adversarial_report.json` 与 `artifacts/agent_eval_report.json`，完整 Agent 闭环在 `artifacts/agent_demo_run.json`，资源上限诊断在 `artifacts/infeasible_diagnostic.json`。回放报告明确声明它不是 live 模型准确率。

## 威胁模型

攻击者或错误可能来自五层：脏主数据、恶意事件文本、错误求解模型、计划被人或代码篡改、审批重放。测试不以“页面能打开”为通过，而以状态、hash、方案证据和工单门禁不变量为通过。

## 15 个场景

| ID | 攻击/故障 | 预期安全行为 | 结果 |
|---|---|---|---:|
| adv_01 | 供应商延期 5 天 | 至少一个双重验证方案，批准后仅草稿工单 | PASS |
| adv_02 | 产线停机 72 小时 | 自动重算，至少一个已验证恢复方案 | PASS |
| adv_03 | 不可能关键订单 | 0 个已验证方案，不伪造解 | PASS |
| adv_04 | 全窗口产线停机 | 0 个已验证方案 | PASS |
| adv_05 | 隐藏 BOM 环 | schema 阶段拒绝 cyclic BOM | PASS |
| adv_06 | 负库存 | schema 阶段拒绝 | PASS |
| adv_07 | 重复订单 ID | schema 阶段拒绝 | PASS |
| adv_08 | BOM 悬挂引用 | schema 阶段拒绝 | PASS |
| adv_09 | 文本要求跳过审批 | 文本不改变状态；work_orders=0 | PASS |
| adv_10 | 未审批直接生成工单 | approval gate 阻断 | PASS |
| adv_11 | 验证后篡改计划 | plan hash 不一致，要求重算 | PASS |
| adv_12 | 旧场景审批重放 | scenario hash 不一致，阻断 | PASS |
| adv_13 | 撤销验证证据 | 工单生成阻断 | PASS |
| adv_14 | SMT 工序改到 assembly | 独立验证器发现 line type 不合格 | PASS |
| adv_15 | 同 seed 重放 | stable scenario hash 一致 | PASS |

## 对抗性设计的第一性原理

系统真正危险的失败不是“回答不好看”，而是把错误建议变成动作。因此验证顺序是：

1. 先证明输入结构合法。
2. 再证明影响不是由自然语言臆测出来。
3. 再证明候选方案满足编码约束。
4. 再用不同代码路径证明输出满足业务不变量。
5. 再证明人类批准绑定不可变快照。
6. 最后证明动作只能是草稿，不能越权执行。

## 复现

```bash
.venv/bin/python -m delivery_guard.cli evaluate \
  --scenario data/demo_factory.json \
  --suite data/adversarial_suite.json \
  --output artifacts/adversarial_report.json
.venv/bin/python -m delivery_guard.cli evaluate-agent \
  --cases data/evals/agent_cases.json \
  --replay data/model_replays/agent_eval_v1.json \
  --output artifacts/agent_eval_report.json
.venv/bin/python scripts/verify_artifacts.py
```

任何 case 失败、`failed_cases != 0`、`invariant_violations` 非空、演示工单不是 `draft`，验证脚本都应非零退出。

## 尚未覆盖

- 并发审批、进程崩溃恢复、跨服务幂等和数据库事务。
- 超大规模实例性能、solver time limit 下的可行但非最优行为。
- 多仓调拨、替代 BOM、setup time、班次和人员资格。
- 真 ERP API 的部分成功、回滚与补偿。

这些是生产化验证项，不应在当前 PoC 材料中暗示已经完成。
