# 答辩 Q&A：不回避的版本

## 这不就是 ERPNext/Odoo/frePPLe 吗？

不是同一层，但它们是必须承认的强基线。ERPNext/Odoo 事务与工单成熟，frePPLe 规划内核成熟。有界没有重造完整 ERP；它验证的是异常处置决策层：结构化事件触发、跨对象影响证据、三类联合求解方案、solver 外领域验证、hash 绑定审批和工单门禁。生产化最合理的路线是接入它们，而不是替代它们。

## AI 会不会只是装饰？

不是。供应商邮件真实进入 `qwen3.8-max` 结构化模型边界，模型负责意图候选、业务字段、原文 span 和安全标记；LangGraph 基于上下文追问、检索政策和编排工具。稳定实体 ID、缺失项、BOM、库存、产能、可行性、审批和执行权限由确定性代码控制。真实黄金集原始模型意图/实体/字段/安全标记为 88.9%/40.0%/95.6%/100%，规则约束后的 Agent 3 轮均为 30/30。这个差值正是安全分工的证据，不是把 Replay 冒充 AI。

## 这是不是传统运筹优化包装一层 UI？

求解器是核心之一，但完整问题还包括事件应用、影响传播、多策略比较、独立业务验证、批准失效、提示注入防护和可审计动作生成。只跑一个 CP-SAT notebook 不会解决“错误建议如何被阻断、谁批准了什么、数据变更后批准是否仍有效”。

## 为什么使用 LangGraph，但不做 CrewAI 式多 Agent 人设？

当前闭环已经迁移到 LangGraph：它负责调查规划、allowlisted 工具路由、checkpoint、人审 interrupt 和恢复。没有把“采购、排产、审批”做成共享同一权限的角色套壳，因为数值和执行权限必须集中受控。随机事故 Agent 只生成合法演练输入，不能求解或审批。

## 求解器返回最优，为什么还验证一次？

solver 只保证“我们编码的模型”有解。约束漏写、单位错误、输出转换错误仍可能得到 `OPTIMAL`。独立 verifier 从输出重建业务规则，而且有专门攻击用例证明它能抓住把 SMT 工序换到 assembly 的篡改。

## 三个方案真有业务差异吗？

有，而且不是改标题：公开数据主场景中，保交付/平衡/少变更分别是 91/45/0 台按时、应急采购 91/45/0 件、恢复成本 ¥728/¥360/¥0。数字全部来自 solver artifact，并由独立 verifier 重放。

## 4 小时时间格会不会错过更优解？

会。这是 PoC 明示的速度/精度折中，不是理论最优保证。工序时长、停机和库存仍按整数小时校验，但候选开始时间只在 4 小时格。真实部署应按场景规模使用更细时间格、interval variables、rolling horizon 或分解算法，并做性能基准。

## 数据是假的，场景真实性在哪里？

不能笼统说“全真”或“全假”。需求、BOM、库存、供应网络和产能来自 Mendeley CC BY 4.0 原始 `.xlsb` 的可追溯行；客户名称、事故邮件、应急供应商、价格、预算和审批是明确标注的 synthetic overlay。公开数据本身也是行业研究中的随机化汽车供应链数据，不是某家企业生产流水，因此只能证明机制与可复现性，不能证明业务收益。下一步必须用授权脱敏的历史异常做离线 replay 和人工基线比较。

## 工单闭环为什么只是草稿？

因为比赛 PoC 不应直接控制真实设备或替代安全生产决策。这里先形成绑定审批和双 hash 的草稿执行意图。真实本机 ERPNext 已实际创建并回读 Material Request / Work Order 草稿；真实 OpenMES 接收同号生产工单并回读应用层执行状态；商业系统的部分失败和异步语义仍由合同沙箱验证。仍不是生产闭环：没有生产租户、厂商认证或物理设备执行。材料可以说“真实开源 ERP→MES 测试链路 + 合同级商业系统回流”，不能说“已完成真实工厂生产写回”。

## OpenMES 是不是你们自己写的一个页面？

不是。运行的是官方 `Mes-Open/OpenMes` AGPL-3.0 仓库，固定到完整 git commit；界面、PostgreSQL 和工单状态机都来自该上游。有界只通过其官方 `/api/v1/erp/*` 接口导入/回读，没有修改 OpenMES 核心，也不读取数据库。我们新增的是有界侧的 adapter、跨系统映射、审批门禁、幂等和 stale-plan 处理。

## ERPNext 和 OpenMES 为什么都有 Work Order，是否重复？

编号相同但职责不同。ERPNext 的 Work Order 是企业层的业务与计划记录；OpenMES 的 Work Order 是现场接单、执行、产量和质量记录。用 ERPNext 工单号作为 OpenMES `order_no`，正是为了让“企业承诺”与“现场事实”能够对账。两边各有一条记录不是重复造单，而是 ISA-95 Level 4→Level 3 的交接；有界必须显示映射关系和状态差异。

## 你说接入 SAP、金蝶、黑湖，证据是什么？

我们没有说已接入 SAP、金蝶或黑湖生产租户。Demo 中除了真实本机 ERPNext 开源测试实例，还运行两个 project-owned contract profile：`sap_s4_dm_contract_profile` 和 `kingdee_blacklake_contract_profile`。ERPNext 证据是实际 REST 记录 ID、GET 回读与 revision；两个合同 profile 证明 canonical 数据、命令、幂等、异步回流和失败语义能够运行。真正接入商业厂商仍要取得租户和授权，补认证、字段映射、分页限流、厂商错误码、回调或轮询及客户验收。

## 为什么选择这两组，而不是声称它们市占率第一？

我们不做跨口径的“第一”结论。国际大型产品型制造企业常见 SAP 生态，国内制造数字化常见金蝶等 ERP 与本土 MES 组合；公开窄口径报告还能支持黑湖在中国 MES 软件收入市场的代表性。选择它们是为了覆盖“国际套件型”和“国内组合型”两种接入形态，不是做厂商排名。完整市场与接口依据在 `semifinal_integration_spec.md`。

## HTTP 202 已经返回，为什么页面不显示成功？

202 只说明对方接收了请求，不能证明采购申请或排程变更已应用。系统把 transport status 和 business status 分开：202 后业务状态仍是 `PENDING`，必须等待带 operation ID、sequence、revision 和 evidence hash 的 callback，或主动查询最终状态。这个区别由 ADV-05 自动测试。

## ERP 成功、MES 失败会不会数据不一致？

会，所以不能假装全局回滚。Demo 明确显示 `PARTIALLY_APPLIED`，保留 ERP 已发生事实；MES 的非重试型版本冲突触发协调与重新规划。生产化需要按目标系统能力定义补偿动作和审批，而不是在本地内存里把 ERP 状态改回去。

## 如果回调重复、乱序或同一个幂等键换了 payload 呢？

outbox/inbox ledger 用 idempotency key、event ID 和 sequence 处理：相同请求只对应一个 operation；同 key 不同 payload 返回冲突；重复 callback 去重；较小 sequence 只留审计记录，不能把 APPLIED 倒退成 PENDING。ADV-03/04/07/08 给出机器可读证据。

## MES 反馈后为什么一定要重新审批？

原批准绑定的是旧 scenario hash 和 plan hash。产能 revision 变化后依赖图和 scenario hash 已改变，旧批准的授权对象不再存在。系统使旧批准失效、重新运行 CP-SAT/verifier，工单保持 0，直到人对新方案再次批准。否则“人工审批”只是装饰。

## 这个系统在 ISA-95 哪一层？

只覆盖 Level 3/4 之间的业务信息、建议、事务草稿和执行反馈；Level 0–2 的设备与过程控制只读，不发 OPC UA write、PLC write 或 method call。禁止设备控制既写在材料里，也在 command schema 中 fail closed。

## 人工审批是不是点一个按钮，太浅？

UI 是按钮，但后端批准记录绑定 actor、comment、scenario hash 和 plan hash。旧快照重放、计划篡改和证据撤销都被测试阻断。当前缺口是持久化、RBAC、双人审批和超时恢复；这些是复赛工程项。

## LLM 能否通过提示注入跳过审批？

不能。真实恶意邮件会经过语言模型，但输出只允许 `IncidentDraft`；“批准/采购”不在该 schema 的能力范围。检索文档也按不可信数据隔离。审批和草稿函数只接受合法 workflow 状态、人工 actor 和有效 hash。30 条 Agent 合同覆盖 prompt injection、retrieval injection、自报 solver 状态和伪造 plan hash，forbidden tool 次数为 0。

## 3 轮 30/30 是否说明模型准确率 100%？

不说明。Live 报告只对 `qwen3.8-max`、当前提示词、当前 endpoint、2026-08-27 和 30 条合成黄金集有效，不代表真实工厂分布或其他模型。仓库还保留了改进过程中的失败报告；最终 3×30 是修正意图边界与规则策略后重新调用得到的，不是把 Replay 分数改名。

## 性能如何？

当前 8 订单、2 产线、14 天的三个 profile 在普通个人电脑上可在数秒量级完成，但这不是规模性能承诺。artifact 记录每个 profile 的 `solve_time_ms`；扩容前必须测试变量规模、time limit、feasible gap 与 rolling horizon。

## 你们的独特护城河是什么？

当前不是数据或算法专利，而是可审计系统设计：统一数据契约、可复算异常套件、双重可行性证据、hash 绑定批准和安全动作门禁。长期价值来自接入企业数据后积累的异常回放集、约束模板、方案接受反馈和 connector，而不是再做一个聊天 UI。

## 现场哪句话绝对不能说？

- 不能说“没有开源项目覆盖这些能力”。
- 不能说“这是首个制造供应链 Agent”。
- 不能说“真实工厂验证提升了 X%”。
- 不能说“已完成真实工厂生产 ERP/MES 闭环”；可以说“已完成真实开源 ERPNext→OpenMES 本机测试链路，并用合同沙箱验证商业系统部分失败”。
- 不能说“SAP/金蝶/黑湖市占率第一”或“已获得厂商认证”。
- 不能说“HTTP 202 代表业务执行成功”。
- 不能说“solver optimal 等于业务一定正确”。
