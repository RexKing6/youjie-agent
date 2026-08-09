# 开源项目与论文对抗性复核

## 修正后的结论

原表述“没有成熟开源项目同时覆盖订单、BOM、库存、供应商交期、有限产能排程、异常重算、人工审批和工单闭环”不能使用。Odoo Community、ERPNext 和 frePPLe 都能按不同口径覆盖其中大多数甚至近乎全部业务对象与流程。

截至 2026-08-08，在本次可复核的 GitHub/GitLab、官方文档和论文范围内，未验证到一个成熟、完全开源、Agent-first 的现成产品，能开箱完成：

> 自然语言异常理解 → 订单/BOM/库存/供应商/产能联合求解 → 可解释方案比较 → 持久人工审批 → 工单写回 → 执行回流。

这是检索范围内结论，不是“不存在”的数学证明；没有对所有候选进行本地部署，也不能排除未索引、私有或后续发布的项目。

## 最强反例矩阵

符号：`✓` 公开实现有明确能力；`△` 部分、手工触发、非联合优化或 open-core 边界；`—` 本次未验证。

| 项目 | 订单/BOM/库存 | 供应交期 | 有限产能 | 异常重算 | 人审 | 工单执行 | Agent-first 联合闭环 | 结论 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Odoo Community 19 | ✓ | ✓ | △ | △ | ✓ | ✓ | — | 成熟事务 ERP；核心有 work-order replan 与采购两步审批，但不是全局异常优化 Agent |
| ERPNext | ✓ | ✓ | △ | △ | ✓ | ✓ | — | 最强事务闭环反例；Production Plan、Workflow、Work Order/Job Card 已成熟 |
| ERPNext + Frappe Assistant Core | ✓ | ✓ | △ | △ | ✓ | ✓ | △ | LLM 可在权限与审计内操作 ERP，但缺专用异常规划器与验证 benchmark |
| frePPLe Community | ✓ | ✓ | ✓ | ✓ | △ | △ | — | 最强 APS baseline；完整 shop-floor/部分计划能力有 open-core 边界 |
| OptiGuide | △ | △ | ✓ | ✓ | △ | — | △ | 最强 LLM+OR 研究基线；无事务、持久审批和工单闭环 |
| OptiRepair | △ | ✓ | ✓ | ✓ | — | — | △ | 证明 feasible 不等于业务合理；不是应用产品 |
| Agentic disruption monitoring | — | ✓ | — | ✓ | ✓ | — | △ | 覆盖异常前半链，缺 BOM/库存/排程/执行 |
| InvAgent | △ | ✓ | — | △ | — | — | △ | 多级库存仿真，不是制造系统 |
| Temporal order repair | ✓ | △ | — | ✓ | ✓ | △ | △ | 耐久人审模式强，业务模型玩具化 |

## 对代码与产品叙事的直接影响

1. 不把订单/BOM/库存 CRUD 当创新；这些已有成熟实现。
2. 不嵌入完整 ERP。Demo 聚焦异常决策的缺口，并设计可映射 ERPNext/Odoo 的数据契约。
3. 把 frePPLe 当 APS baseline：它擅长联合规划；有界的新增价值是事件化影响证据、三方案对比、双重验证、显式批准哈希和可公开复现的攻击套件。
4. 采纳 OptiGuide 的原则：LLM 只触发受控模型与工具，数值结果来自 solver。
5. 采纳 OptiRepair 的反例：solver 可行仍需领域合理性硬验证。
6. 采纳 Temporal 样例的工程教训：人审必须有状态与审计，不是聊天里问一句“确认吗”。

## 论文证据

- [OptiGuide](https://arxiv.org/abs/2307.03875) 及其 [官方代码](https://github.com/microsoft/OptiGuide) 展示自然语言 what-if、受控模型修改、重新求解与解释，但没有订单事务和工单执行。
- [OptiRepair](https://arxiv.org/abs/2602.19439) 在 976 个供应链恢复问题、22 个 API 模型上区分 feasibility 与 operational rationality；论文报告最佳 API 模型 Rational Recovery Rate 仍为 42.2%，所以本项目增加独立验证器和领域不变量。
- [Automating Supply Chain Disruption Monitoring via an Agentic AI Approach](https://arxiv.org/abs/2601.09680) 覆盖事件筛选、图传播、缓解建议与 human review，但使用合成汽车场景和静态图，未公开证明制造排程与工单闭环。
- [InvAgent](https://arxiv.org/abs/2407.11384) 与 [代码](https://github.com/zefang-liu/InvAgent) 适合库存 Agent 研究，不包含 BOM、工序产能或审批。
- [供应链 LLM 系统综述](https://doi.org/10.1080/00207543.2026.2641103) 支持“研究碎片化、缺统一评测”的判断，但不能代替逐仓库功能审计。

## 主要开源证据

- Odoo [仓库](https://github.com/odoo/odoo)、[MRP replan 源码](https://github.com/odoo/odoo/blob/19.0/addons/mrp/models/mrp_production.py#L1708-L1745)、[采购两步审批源码](https://github.com/odoo/odoo/blob/19.0/addons/purchase/models/purchase_order.py#L615-L639)。
- ERPNext [仓库](https://github.com/frappe/erpnext)、[Production Plan](https://docs.frappe.io/erpnext/production-plan)、[Capacity Planning](https://docs.frappe.io/erpnext/capacity-planning)、[Workflow](https://docs.frappe.io/erpnext/workflows)、[Work Order](https://docs.frappe.io/erpnext/work-order)。
- [Frappe Assistant Core](https://github.com/buildswithpaul/Frappe_Assistant_Core) 与正在讨论的 [Agentic Stock Reservation 提案 #52618](https://github.com/frappe/erpnext/issues/52618)。
- frePPLe [仓库](https://github.com/frePPLe/frepple)、[Manufacturing Orders](https://frepple.com/docs/current/model-reference/manufacturing-orders.php)、[Constrained Planning](https://frepple.com/docs/current/modeling-wizard/generate-plan.php)、[Release Notes](https://frepple.com/docs/current/release-notes.html)。

## 最可能推翻本结论的未来证据

- ERPNext #52618 合并并加入有限产能异常重排与可复现实验。
- ERPNext + FAC 发布开源供应链 solver app，含事件触发、备选方案、审批和回写测试。
- frePPLe Community 发布原生 Agent、通用审批和双向工单执行回流。
- OptiGuide/OptiRepair 发布 ERP connector，把真实订单与资源经过双重验证后写回。

因此最终材料始终使用“本次未验证到”，并在提交前重新检查上述高风险候选。
