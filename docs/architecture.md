# LangGraph 架构与可信边界

## 架构结论

有界是一个 LangGraph 单 Agent 控制面和确定性可信内核。没有用多个人设 Agent 包装同一模型；随机事故 Agent 是独立的演练输入生成器，不参与求解或审批。

```mermaid
flowchart TB
  subgraph Data["数据与输入"]
    X["Mendeley .xlsb\nhash + sheet rows"]
    O["Synthetic overlay\n邮件/聊天/成本/审批"]
    C["ChaosDrillAgent\nseeded bounded incident"]
  end
  subgraph Graph["LangGraph control plane"]
    U["understand_incident"]
    Q["clarify_incident interrupt"]
    P["plan_investigation"]
    T["execute_investigation"]
    S["analyze_and_solve"]
    H["human_approval interrupt"]
    D["draft_actions"]
  end
  subgraph Kernel["Deterministic trust kernel"]
    V["Pydantic IDs / ranges"]
    I["BOM impact"]
    CP["OR-Tools CP-SAT"]
    R["Independent verifier"]
    W["RecoveryWorkflow"]
  end
  X --> V
  O --> U
  C --> V
  U --> Q --> P
  U --> P --> T --> S
  T --> V
  S --> I --> CP --> R --> H
  H -->|approve| D --> W
  H -->|reject| E["END / zero actions"]
```

## 图节点

| 节点 | 职责 | LLM 权限 |
|---|---|---|
| `understand_incident` | 邮件转 `IncidentDraft`，或校验演练 ground truth | 只能提出候选字段与 source span |
| `clarify_incident` | 缺失、冲突或确认项触发动态 interrupt | 无求解和执行权限 |
| `plan_investigation` | 按事故类型选择 allowlisted 查询、检索、分析、求解动作 | 不能创建新工具名 |
| `execute_investigation` | 冻结快照、检索政策并记录引用 | 文档是数据，不能改权限 |
| `analyze_and_solve` | 调用影响引擎、三策略 CP-SAT、独立 verifier | LLM 不参与数值计算 |
| `human_approval` | LangGraph checkpoint + interrupt，等待批准或驳回 | 只有人能作决定 |
| `draft_actions` | 从原场景重算，核对 scenario/plan hash，再生成草稿 | 不能执行外部写回 |

图使用 `InMemorySaver` 和稳定 `thread_id` 演示暂停/恢复。生产化需要 SQLite/Postgres 等持久 checkpointer、加密、RBAC 和多实例幂等。

## 为什么批准后再求解一次

LangGraph interrupt 期间外部事实可能变化。恢复后系统不直接相信审批前的内存对象，而是：

1. 从原 Scenario 和 Incident 重建 `RecoveryWorkflow`；
2. 重新运行影响分析、CP-SAT 和 verifier；
3. 比较新的 `scenario_hash` 与审批看到的 hash；
4. 比较候选 `plan_hash` 与审批看到的 hash；
5. 两者一致才创建审批记录和 `draft_only` 工单。

这使“旧页面批准”“篡改候选 JSON”和“断点后场景变化”无法静默越权。

## 求解硬约束

- 工序产线资格、时间窗、release、前置关系和资源互斥；
- 供应来源容量、禁用状态、承诺下限和到货时间；
- BOM 展开后的逐事件库存守恒；
- critical/frozen 订单不得静默放弃；
- 恢复预算上限；
- 所有计划必须由独立 verifier 从输出 JSON 重放。

三个 profile 只改变服务、延迟、恢复成本和动作数量权重/预算，不改变硬约束。

## 随机事故 Agent

`ChaosDrillAgent` 从已验证场景实体采样，支持：

- supplier delay / shutdown；
- inventory loss（不超过可用库存）；
- line outage（窗口在 horizon 内）；
- demand surge（目标必须是已存在订单）。

它输出结构化 Incident 和模拟邮件/聊天/MES 文案。文字仍是不可信展示数据；实际变更只来自通过 Pydantic 的 Incident。相同 seed 完全复现。

## 生产化缺口

- 持久 checkpointer、审批 RBAC、双人复核、审计签名；
- ERP/MES staging connector、outbox/saga、幂等写入和补偿；
- 多工厂、多仓、在途、替代料、setup、人员技能和分时供应容量；
- 授权脱敏历史事故回放与真实人工基线；
- live 模型单独评测，不能拿 replay 合同替代泛化准确率。
