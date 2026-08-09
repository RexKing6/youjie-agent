# Agent 回放评测摘要

- 模式：`replay`
- 模型标识：`delivery-guard-recorded-eval-replay-v1`
- 数据版本：`2026-08-09.v1`
- 结果：30/30 passed
- 重复运行：2 次，结构化输出完全一致
- 禁止工具调用：0
- 对抗安全样例：4/4 passed

重要边界：这是人工复核的版本化结构化回放，用于离线回归，不是 live 模型准确率声明。逐案输入、黄金动作、实际动作与检查结果见同目录 `agent_eval_report.json`。
