# 数据来源、逐行溯源与模拟边界

## 结论

当前主演示实际使用公开工作簿原始行，不再只是 schema 参考。公开事实和模拟字段分成两层，并由 `lineage.json` 逐项记录。

## 公开层

- 数据集：Mendeley Data，[Optimisation model for multi-item multi-echelon supply chains with nested multi-level products](https://data.mendeley.com/datasets/pr3sdy5vp3/1)。
- DOI：`10.17632/pr3sdy5vp3.1`，Version 1，发布于 2020-05-09。
- 作者：Andre Moetz、Mathias Quetschlich、Boris Otto。
- 许可：CC BY 4.0。
- 原文件：`data/public/mendeley_automotive/2020_dataset_automotive_production_network.xlsb`。
- SHA-256：`1ea0bcdea3225d308be913c9ca0f377585e1863847c78d6e8eec10b6de82889e`。

原工作簿含 28,049 个产品、12 个节点、11 条弧、87,059 条 BOM、28,000 条需求，以及库存、逐期产能、提前期和初始流。它是汽车供应链案例背景下的随机化数据，不是企业原始生产流水。

## 本案例选择规则

`scripts/build_mendeley_case.py` 调用 `build_public_scenario()`：

1. 先校验整个 `.xlsb` 的 SHA-256；不一致立即失败。
2. 读取 `products`、`BOM`、`demands`、`initial_inventories`、`arcs`、`capacity_at_arc`。
3. 选择 `demands.period_t = 61` 且 BOM 签名为以下三种的逐车需求行：
   - `DG8 + G0K + Q2J`：91 行；
   - `DK8 + G0K + Q2J`：81 行；
   - `D83 + G1Z + BEV + Q2J`：45 行。
4. 相同 BOM 签名聚合为一张比赛订单；每个原始车辆 `product_p`、需求值和工作表行号保留在 `lineage.json`。
5. 校验：原始需求行数 217、原始需求和 217、聚合订单和 217。

公开 BOM、`zp7` 初始库存、供应弧提前期、Q2J 所属 seat 弧 2,100 单位容量、`zp7 -> zp8` 每期 2,000 单位容量均保留原表行号。

## 必要转换

| 转换 | 原因 | 边界 |
|---|---|---|
| 逐车需求按相同 BOM 聚合 | 当前求解器面向订单数量，不适合展示 217 张单车订单 | 总量严格守恒，原行未丢失 |
| 期 61 映射为 `due_hour=24` | 领域模型使用整数小时 | 这是演示时间映射，不是原字段 |
| Q2J 使用 seat 弧容量作为上限 | 原数据该处为产品组容量 | 本子集只选择 Q2J；最大承诺被收紧为本案例需求 217，不冒充产品级原值 |
| 每日 2,000 容量映射为 5 个 4 小时、每批 400 的窗口 | 当前 solver 使用离散工序窗口 | 只用于 PoC 排程，不声称还原原论文模型 |
| 去掉 BOM 自引用行 | 原表的自引用表达工序流转；领域 BOM 禁止循环 | 自引用行不作为物料消耗 |

## 模拟覆盖层

公开工作簿没有客户名称、优先级、SLA、应急供应商报价、事故邮件、聊天记录或审批。因此以下字段由 seed `20260809` 确定性生成并明确标注：

- 三个客户名称与 critical/high/normal 优先级；
- Q2J 应急来源：12 小时、最多 100 件、每件恢复成本 8 元；
- 三个策略的恢复预算 800 / 400 / 0 元；
- Q2J 基础来源延迟 48 小时的模拟邮件；
- `ChaosDrillAgent` 生成的供应、库存、产线和需求事故；
- 人工审批人、意见和草稿工单。

复赛另增加三个多格式证据 fixture，仍属于确定性模拟层：

- `supplier_email.png` / `.eml`：48 小时，PNG 绑定预计算 OCR 文本和 bbox；
- `carrier_notice.pdf`：72 小时，PDF 绑定第 1 页文字层位置；
- `mes_snapshot.csv`：48 小时，但在案例时点已过期 26 小时。

`evidence/manifest.json` 为每个文件记录 SHA-256、媒体类型、观察时点、抽取方式、原文位置和新鲜度策略。二进制内容永远只作为不可信数据，不能修改工具权限或审批门。

模拟层使用 Apache-2.0。它不能被描述为 Mendeley 原始事实或真实企业价格。

## 许可与安全

- Mendeley 原数据和直接派生行：CC BY 4.0，必须保留署名、链接和修改说明。
- 本项目代码与模拟覆盖层：Apache-2.0。
- LangGraph：MIT；OR-Tools：Apache-2.0；Pydantic：MIT；Streamlit：Apache-2.0；Altair：BSD-3-Clause。
- 不使用阿里云内部数据、日志、规则或客户信息。
- 随机事故只修改内存中的场景副本，不控制设备、不连接 ERP/MES、不发送真实采购。

## 不能声称的内容

- 不能说这是某家汽车企业的真实原始生产数据。
- 不能用三张聚合订单证明真实工厂收益、吞吐或规模性能。
- 不能把模拟应急成本和策略预算归因于数据集作者。
- 不能用 replay 结果声称在线大模型准确率。
