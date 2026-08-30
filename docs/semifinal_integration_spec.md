# 有界·复赛补强 SPEC

## 恢复方案可视化与 ERP/MES 执行回流闭环

> 文档状态：`IMPLEMENTATION BASELINE`
> 版本：`v1.1`
> AS_OF：`2026-08-30`
> 目标版本：GOAI 2026「无界应用」复赛提交版
> 截止时间：`2026-09-03 18:00 UTC+8`
> 本轮边界：本 SPEC 先供讨论；未开始修改应用代码、密钥、部署或公开仓库。

## 0. 决策摘要

当前版本不是重做，而是在现有 LangGraph + CP-SAT + verifier + 人工审批内核外增加三个评委可见层：

1. **恢复指挥台**：三方案同屏甘特图、订单影响图、交付/成本/资源调整对比。
2. **ERP/MES 集成沙箱**：真实运行 HTTP/JSON 命令、异步 ACK/回调、部分失败、旧计划失效和重新求解；所有端点都是本项目自建 `/sandbox/v1/...`，明确标注为 `protocol compatibility sandbox`，不冒充真实 SAP、用友、金蝶、西门子或其他厂商租户。
3. **真实开源双系统测试链路**：ERPNext v16 测试实例负责采购申请与生产工单草稿；OpenMES 固定上游提交 `f0ccdd1c7a57804212ed337d340aebfeebacc372` 负责接收批准后的工单、记录现场执行状态并向有界提供增量回读。两套系统均仅在本机测试环境运行。

真实开源链路的角色边界固定为：

- ERPNext：Level 4 业务事实与授权后草稿记录，不负责证明车间已经执行。
- OpenMES：Level 3 工单、工序、报工、质量与完成状态，不替代 ERP 的采购、库存财务或组织审批。
- 有界：映射 ERP 工单到 MES 工单，保留源单号、场景 hash、计划 hash 与审批 ID；回读 MES 状态并判断旧计划是否失效。
- 人：在 ERP/MES 中执行提交、排产、开工、报工或异常处理；Agent 不调用设备控制端点。

OpenMES 选择依据来自其官方仓库与当前代码，而非名称判断：AGPL-3.0；提供 `/api/v1/erp/work-orders/import`、`/api/v1/erp/work-orders/{id}`、`/api/v1/erp/production/completions`、质量问题回读、按 scope 的 API Key，以及工单状态 Webhook。真实演示只使用工单导入和只读回读，不启用设备命令。

P0 底层只实现两个协议引擎：

- `erp_transaction_adapter`：REST/JSON 为运行路径，兼容 OData 式实体读取、异步业务事件、SFTP/CSV 降级语义；用于订单、BOM、库存、供应承诺、采购申请草稿和订单风险状态。
- `mes_operations_adapter`：REST/JSON 命令 + CloudEvents 式回调为运行路径，MQTT/OPC UA 仅做只读事件 Replay；用于产能、停机、排程变更草稿和执行反馈。

在两个引擎之上做两个可运行、深度验收的厂商组合 **contract profile**：

- `sap_s4_dm_contract_profile`：SAP S/4HANA Cloud + SAP Digital Manufacturing，代表国际大型制造企业常见组合。
- `kingdee_blacklake_contract_profile`：金蝶星瀚/星空风格 ERP + 黑湖 MES 风格 OpenAPI，代表中国制造企业数字化组合。

两者均固定显示 `CONTRACT-COMPATIBLE SANDBOX · NON-CERTIFIED · NO LIVE TENANT`。其余厂商只进入映射矩阵，不做浅层假连接器。

厂商映射蓝图覆盖：

- ERP：SAP S/4HANA、Oracle Fusion Cloud ERP/SCM、Microsoft Dynamics 365 F&O、用友 YonBIP/U9 Cloud、金蝶星瀚/星空，Infor 作为扩展。
- MES/MOM：Siemens Opcenter、SAP Digital Manufacturing、Rockwell Plex/FactoryTalk、DELMIA Apriso、GE Proficy、黑湖；宝信和鼎捷只列市场/产品参考，不虚构公开端点。

不做：真实企业系统账号、生产写入、PLC/DCS/机器人控制、五个浅薄“厂商连接器”、与评委无关的通用聊天功能。OpenMES 自带 PostgreSQL/队列仅作为该开源测试产品的运行依赖，不进入有界的业务架构，也不作为比赛创新点。

## 1. 背景与需求追踪

复赛规则要求 Demo 可运行、任务链路完整、工程材料可访问、数据与合规边界明确；完整链路必须展示用户输入、Agent 处理、工具或知识库调用、结果交付、异常处理和效果验证。[1]

本项目收到两条定向建议：[2]

| 评委建议 | 当前已有 | 真实缺口 | 本 SPEC 对策 |
|---|---|---|---|
| 甘特图、订单影响图与方案差异可视化 | 单方案时间轴；91/45/0、¥728/360/0 指标卡 | 只能逐个方案看；无订单影响关系图；资源调整不直观 | 三方案同轴小多图 + 影响 DAG + KPI/资源变化矩阵 |
| 在线模型与多轮稳定性 | `qwen3.8-max` 3×30，共 90 次真实调用 | 不是端到端多轮业务会话稳定性 | 新增 10 次完整 Live 会话和回流重算稳定性 |
| ERP/MES 对接及执行结果回流 | MES CSV 输入；批准后生成 `draft_only` 工单 | 没有适配器、ACK、失败回流和重算 | 本地 HTTP 沙箱 + Outbox + ACK/Callback + Stale/Replan |

当前业务内核继续复用：严格领域模型、BOM/库存/供应/产能影响计算、三策略 CP-SAT、独立 verifier、LangGraph interrupt、批准后双 hash 复核和草稿工单。关键代码位于 `src/delivery_guard/models.py`、`graph.py`、`solver.py`、`verifier.py` 和 `orders.py`。

## 2. 市场与厂商选择

### 2.1 先限定“市占率”的口径

不能写一句“SAP/西门子市占率最高”然后结束。ERP/MES 的排名会因全球/中国、收入/装机量、软件/软件加服务、大型企业/中小企业、离散/流程制造而变化。

- CAICT 的企业 SaaS 报告给出特定中国 ERP 口径的数据；另一份专精特新企业调研给出的 ERP 工具使用 Top 5 是金蝶、用友、鼎捷、SAP、自研，但没有可互换的统一份额。[3][4]
- Gartner 的产品型企业云 ERP 范围可支持 SAP、Oracle、Microsoft、Infor 是国际大型制造企业的代表性候选，但不等于中国制造市占率排名。[5]
- Gartner 2026 MES 公开摘要使用“代表性厂商”而不是公开全球份额榜，因此国际 MES 产品不做伪精确排名。[13]
- 可公开复现的较窄口径是 2024 中国 MES **软件收入**：行业报告图表给出宝信 9.3%、黑湖 8.8%、西门子 6.3%。这只能用于说明中国市场代表性，不能外推为 2026、全球或软件加服务份额。[14]

**SPEC 文案规则：**有一致公开数字时同时写口径、年份和来源；没有时写“代表性大型企业产品”或“目标客户常见候选”，不写“第一”“最大份额”。

### 2.2 ERP 代表产品与接入方式

| 产品族 | 选择理由 | 官方可核验接入面 | 本项目处理 |
|---|---|---|---|
| SAP S/4HANA | 国际大型产品型制造企业代表 | OData V2/V4、SOAP；既有环境可能用 BAPI/IDoc；Business Events [6][7] | `sap_s4_dm_contract_profile` 的 ERP 映射；不称 SAP 认证连接器 |
| Oracle Fusion ERP/SCM | 国际云 ERP/SCM 代表 | REST/JSON；FBDI CSV+ZIP 批量导入和任务状态/回流 [8] | 文档映射；P1 可加批量导入失败样例 |
| Dynamics 365 F&O | 国际云 ERP 代表 | OData V4、DMF package REST、Data Events；事件可能乱序 [9][10] | 用乱序事件作为对抗样例 |
| 用友 YonBIP/U9 Cloud | 中国大型/制造 ERP 代表 | API Gateway、OpenAPI、授权/限流/熔断；具体 payload 依租户 [11] | OpenAPI 风格映射蓝图；不伪造统一 endpoint |
| 金蝶星瀚/星空 | 中国大型/中型企业应用代表；苍穹本身是 PaaS | RESTful OpenAPI、查询/保存/提交/审核、开放事件；依产品版本 [12] | 显式展示 draft→submit→approve 概念映射 |
| Infor LN/CloudSuite | 制造 ERP 扩展代表 | ION/API Gateway、OData/REST、BOD/XML；细节需 tenant | 只进扩展矩阵，不进 P0 运行 Demo |

### 2.3 MES/MOM 代表产品与接入方式

| 产品族 | 选择理由 | 官方可核验接入面 | 本项目处理 |
|---|---|---|---|
| Siemens Opcenter | 国际大型制造 MOM/MES 代表；在中国 MES 软件收入窄口径中也有可见度 | REST、MQTT、OPC UA、文件、SAP IDoc、store-and-forward [15] | 扩展映射矩阵；P0 不做第三个运行 profile |
| SAP Digital Manufacturing | 与 SAP ERP 闭环清晰 | OData/REST、HTTPS/Cloud Integration、OAuth2 client credentials、ERP return path [16] | `sap_s4_dm_contract_profile` 的 MES 映射 |
| Rockwell Plex/FactoryTalk | 云 MES/集成平台代表 | 订单、发运、排序等 secure API；详细 portal 受限 [17] | 只用公开事务类别，不复制虚构 endpoint |
| DELMIA Apriso | 大型制造运营平台代表 | Web API、Web Services、Message Bus、XML/SAP 集成；详细文档需登录 [18] | SOAP/XML/message-bus 扩展映射 |
| GE Proficy | 离散/流程/混合制造代表 | REST/SOAP、OPC UA、MQTT、MTConnect、SAP/Oracle connectors [19] | 事务/遥测两类能力映射 |
| 黑湖 | 中国市场代表，公开 OpenAPI 类别较清晰 | HTTPS OpenAPI、物料/工单/报工与事件 callback [20] | `kingdee_blacklake_contract_profile` 的 MES 映射；不称已通过黑湖认证 |
| 宝信/鼎捷 | 中国市场或制造软件代表 | 产品级公开集成说明；无足够公开版本化 endpoint | 只列市场和扩展对象，不做运行 Profile |

### 2.4 为什么不直接装一套 ERPNext/Odoo

这轮评委要验证的不是“我们会安装 ERP”，而是异常决策 Agent 如何读状态、生成可验证恢复方案、经过人审后安全交付，并处理外部结果回流。临时安装完整 ERP 会消耗时间在账套、权限、主数据和 UI，而不能证明 SAP/用友/金蝶/主流 MES 的接入能力。协议级沙箱能更直接验证接口合同、幂等、异步回流和失败语义；生产接入仍需厂商 tenant、授权、网络、字段映射和客户验收。

**置信度：中高。**厂商协议能力主要来自官方文档；精确市场份额证据薄弱，因此只把狭窄中国 MES 数字作为背景，不让其决定技术范围。

## 3. 产品目标、非目标与用户

### 3.1 目标

- 让制造计划员在 60 秒内看懂异常影响和三种恢复策略差异。
- 证明 Agent 能从 ERP/MES 式快照读取业务事实，而不是把数据全部塞进 Prompt。
- 证明写回前有人审、重算、双 hash 和确定性策略门禁。
- 证明 HTTP 接收成功不等于业务执行完成，系统能等待 ACK/Callback。
- 证明 ERP/MES 部分失败、乱序、超时或状态变化会进入可追踪分支。
- 证明外部事实变化会使旧计划失效并触发重新求解/重新审批。

### 3.2 非目标

- 不连接真实生产 ERP/MES，不申请/存储厂商密钥。
- 不直接控制设备，不发 OPC UA Write/MethodCall，不写 PLC/DCS/机器人。
- 不宣称协议沙箱等于生产认证或实现了所有厂商接口。
- 不实现完整 ERP、MES、ESB、数据湖、消息队列或 CMMS。
- 不把模型输出作为可行性、审批或执行结果。

### 3.3 用户角色

| 角色 | 任务 | 权限 |
|---|---|---|
| 制造计划员 | 查看影响、比较方案、发起审批 | 只读业务事实、选择候选 |
| 审批人 | 批准/驳回恢复方案 | 绑定场景/计划 hash 的一次性批准 |
| 集成运维员 | 查看适配器、失败、重试和 DLQ | 不能更改求解结果或代替审批 |
| 系统/评委观察者 | 重放案例、检查证据 | 无生产权限、无需厂商账号 |

## 4. 主 Demo 用户故事

### 4.1 主链路

1. ERP 沙箱提供 217 台订单、BOM、库存和供应承诺快照；MES 沙箱提供产线能力和当前状态。
2. 供应商邮件报告 Q2J 座椅延迟 48 小时。
3. Agent 识别异常、解析实体、查 ERP/MES canonical snapshot，并调用影响分析。
4. 恢复指挥台显示供应商→物料→3个产品/订单→产线的影响 DAG。
5. CP-SAT 生成“保交付/平衡/少变更”三种方案；页面同屏展示甘特图、按时量、延期量、恢复成本、应急采购和资源变化。
6. 人工批准“平衡方案”。系统从最新快照重新计算 `scenario_hash`，重新求解并核对 `plan_hash`。
7. 系统生成两个 canonical command：ERP采购申请草稿、MES排程变更草稿，写入 Outbox。
8. 本地 HTTP 沙箱首先返回 `202/transport ACCEPTED/business PENDING`；UI 只能显示“已接收/执行中”。
9. ERP 回调 `APPLIED` 并返回采购申请外部编号；MES 回调 `REJECTED`，原因是产线版本已变化。
10. 整体状态变为 `PARTIALLY_APPLIED`，而不是“完成”。系统保留 ERP 已发生事实并给出补偿/人工处置建议。
11. MES 同时回流新的停机事件；命中计划依赖，旧计划变为 `STALE`，取消尚未发送的命令。
12. LangGraph 回到影响分析/求解节点，生成新方案并再次等待审批。系统不能复用旧批准。

### 4.2 2分30秒视频节奏

| 时间 | 展示 |
|---|---|
| 0:00–0:20 | ERP/MES沙箱连接状态、快照版本、公开/模拟数据边界 |
| 0:20–0:45 | 邮件输入、Agent节点和证据引用 |
| 0:45–1:15 | 订单影响图与三方案同屏甘特/KPI |
| 1:15–1:35 | 人审、双 hash 复核、Outbox 命令 |
| 1:35–1:55 | HTTP 202 与最终 ACK 的区别；ERP成功/MES失败 |
| 1:55–2:20 | MES停机回流、旧计划失效、自动重算、重新等待审批 |
| 2:20–2:30 | 稳定性与对抗测试证据、边界收束 |

## 5. 目标架构

ISA-95 将 Level 4 ERP 与 Level 3 MES/MOM 的业务信息交换作为企业—制造集成边界；Level 0–2 涉及物理过程、传感和控制。[21] 本项目只覆盖 L3/L4 的建议、事务草稿和反馈，OT 事件只读。

```text
供应商邮件 / PNG / PDF
            │
            ▼
LangGraph Agent Control Plane
理解 → 澄清 → 调查计划 → 工具调用 → 影响分析
            │
            ├──────────────┐
            ▼              ▼
Canonical Snapshot     Knowledge/Evidence
ERP订单/BOM/库存       hash/locator/freshness
MES产能/状态
            │
            ▼
CP-SAT → Independent Verifier
            │
            ▼
Recovery Command Center
影响图 / 3方案甘特 / KPI / 人工审批
            │
            ▼
Policy Gate + Hash Recheck
            │
            ▼
Transactional Outbox
     ┌──────┴──────┐
     ▼             ▼
ERP Adapter      MES Adapter
REST/OData       REST/Event
     │             │
     └── ACK / Callback / Failure ──┐
                                    ▼
                         Inbox + Dedupe + Audit
                                    │
                    ┌───────────────┴──────────────┐
                    ▼                              ▼
                 Reconciled                  Scenario changed
                                                STALE → replan
```

OData 用于实体读取、ETag 并发和 delta 增量；OpenAPI 描述同步 HTTP，AsyncAPI 描述消息通道，CloudEvents 统一事件上下文，三者职责不同。[22][23][24][25]

## 6. 运行 Profile 与端点

### 6.1 P0 运行方式

仓库提供一个本地 HTTP 沙箱进程：

```bash
python -m delivery_guard.integration_sandbox --port 8601
streamlit run app.py --server.port 8502
```

离线 ZIP 仍允许 Embedded Replay；视频与本地验收必须使用 HTTP 模式证明网络边界、超时、重试和回调真实发生。

### 6.2 自有端点

所有端点使用项目自有命名，不复制厂商路径：

| 方法 | 路径 | 语义 |
|---|---|---|
| GET | `/sandbox/v1/erp/snapshots/{scenario_id}` | 订单、BOM、库存、供应承诺快照 |
| GET | `/sandbox/v1/mes/snapshots/{scenario_id}` | 产能、资源状态、当前排程快照 |
| POST | `/sandbox/v1/commands` | 接收 ERP/MES canonical command，返回 transport ACK |
| GET | `/sandbox/v1/operations/{operation_id}` | 查询异步业务状态 |
| POST | `/youjie/v1/callbacks` | 接收业务执行结果回调 |
| POST | `/sandbox/v1/events/replay` | 注入经过校验的 MES/ERP 事件 |
| GET | `/sandbox/v1/audit/{correlation_id}` | 返回脱敏审计链 |

### 6.3 两个 P0 Contract Profile

| Profile | 输入读取 | 输出命令 | 回流 | 认证Fixture | Demo声明 |
|---|---|---|---|---|---|
| `sap_s4_dm_contract_profile` | S/4 OData式订单/库存/BOM；DM REST式产能/状态 | ERP采购申请草稿、订单风险更新；DM排程变更草稿 | Business Event/HTTP callback式 | OAuth2 client-credentials fixture；无真实secret | SAP公开模式的协议兼容沙箱，非认证、无tenant |
| `kingdee_blacklake_contract_profile` | 金蝶OpenAPI式业务查询；黑湖REST式物料/工单/产能查询 | 金蝶式 `save→submit` 草稿流程；黑湖式排程变更请求 | 开放事件/Webhook式 | Token reference fixture；无真实token | 国产OpenAPI模式的协议兼容沙箱，非认证、无tenant |

主视频选择 `kingdee_blacklake_contract_profile`，因为它更贴近中国制造语境；答辩保留一键切换 `sap_s4_dm_contract_profile`，证明同一 canonical contract 可以跨两个组合。两个 profile 使用同一业务内核和状态机，只替换 mapping、transport fixture、错误码与展示字段，避免复制两套业务逻辑。

金蝶侧只允许创建/保存/提交“待目标系统审批”的草稿，不模拟调用厂商 `audit/approve`；本项目的人审解决的是“是否允许把本计划交付给目标系统”，不能冒充目标 ERP 自身的组织审批。

### 6.4 能力声明

每个 adapter 必须暴露：

```json
{
  "profile": "kingdee_blacklake_contract_profile",
  "environment": "sandbox",
  "sync": true,
  "async_callback": true,
  "supports_idempotency": true,
  "supports_optimistic_lock": true,
  "supports_partial_success": true,
  "supports_compensation": "draft_only",
  "device_control": false
}
```

## 7. Canonical 数据契约

### 7.1 公共元数据

| 字段 | 必填 | 说明 |
|---|---:|---|
| `schema_version` | 是 | `youjie.canonical/v1` |
| `entity_type` / `entity_id` | 是 | canonical 类型和稳定 ID |
| `tenant_id` / `site_id` | 是 | 租户与工厂边界 |
| `source_system` | 是 | 原系统；Demo必须带 `_sandbox` |
| `source_record_id` / `source_revision` | 是 | 原主键与 ETag/row version/change number |
| `observed_at` | 是 | RFC3339，统一保存 UTC |
| `effective_from/to` | 否 | 业务有效区间 |
| `lineage` | 是 | endpoint/file/event、mapping version、raw payload hash |
| `quality` | 是 | freshness、missing、conflict、assumption |
| `payload` | 是 | 业务字段 |

### 7.2 ERP 输入映射

| Canonical实体 | 当前模型 | 最小字段 |
|---|---|---|
| `order` | `CustomerOrder` | order/product/qty/release/due/priority/status/version |
| `bom` | `BomLine` | parent/component/qty/revision/effective window |
| `inventory` | `Inventory` | item/location/on_hand/reserved/quality_hold/version |
| `supplier_commitment` | `SupplierSource` | supplier/item/qty/ETA/lead_time/cost/version |

### 7.3 MES 输入映射

| Canonical实体 | 当前模型 | 最小字段 |
|---|---|---|
| `capacity` | `ProductionLine` | line/type/available windows/unavailable windows/cost/version |
| `routing` | `RouteOperation` | operation/product/sequence/eligible line/batch/duration |
| `resource_status` | `Incident.LINE_OUTAGE` 或状态事件 | resource/status/reason/valid window/safety flag |
| `execution_feedback` | 新增 | command/status/actual qty/time/error/source revision |

数量、单位、金额和时间必须规范化后才计算 hash；未知字段为 `null + quality.missing_fields`，不能由 Agent 猜测。

## 8. Command、ACK 与 Callback

### 8.1 Command Envelope

```json
{
  "specversion": "1.0",
  "id": "cmd_...",
  "source": "urn:youjie:recovery-orchestrator",
  "type": "com.youjie.erp.purchase_requisition.create.v1",
  "time": "2026-08-29T10:20:30Z",
  "correlation_id": "cor_...",
  "causation_id": "plan_...",
  "idempotency_key": "sha256:...",
  "scenario_hash": "sha256:...",
  "plan_hash": "sha256:...",
  "approval_id": "apr_...",
  "approval_expires_at": "2026-08-29T12:20:30Z",
  "expected_source_revision": "rev-17",
  "target": {"system": "erp_sandbox", "environment": "sandbox"},
  "data": {"command_type": "CREATE_PURCHASE_REQUISITION_DRAFT", "payload": {}}
}
```

`id` 是消息身份，`idempotency_key` 是业务副作用身份，不能混用。所有写请求必须同时通过 approval、scenario hash、plan hash、scope、schema 和 expected revision 校验。

### 8.2 Transport ACK

```json
{
  "command_id": "cmd_...",
  "operation_id": "op_...",
  "transport_status": "ACCEPTED",
  "business_status": "PENDING",
  "duplicate": false,
  "errors": []
}
```

HTTP 202/ACK 只表示收到，不能在 UI 写“执行完成”。HTTP 语义也不保证 POST 天然幂等，因此必须使用应用级幂等键。[27]

### 8.3 Business Callback

```json
{
  "specversion": "1.0",
  "id": "evt_...",
  "source": "urn:youjie:mes-sandbox:plant-01",
  "type": "com.youjie.command.execution.v1",
  "correlation_id": "cor_...",
  "command_id": "cmd_...",
  "operation_id": "op_...",
  "scenario_hash": "sha256:...",
  "plan_hash": "sha256:...",
  "business_status": "REJECTED",
  "source_revision_after": "rev-18",
  "errors": [{"code": "STALE_CAPACITY", "message": "line availability changed"}]
}
```

CloudEvents 的 `source + id` 可用于事件重复识别，但业务副作用仍需独立 idempotency key。[25]

## 9. 状态机与一致性

```text
DRAFT
  → APPROVED
  → QUEUED
  → SENT
  → TRANSPORT_ACCEPTED
  → BUSINESS_PENDING
  → APPLIED | PARTIALLY_APPLIED | REJECTED | FAILED | TIMEOUT_UNKNOWN

任何依赖事实变化：
APPROVED/QUEUED/SENT/PENDING → STALE → REPLAN_REQUIRED → AWAITING_APPROVAL
```

规则：

- 审批与 Outbox 必须在同一持久事务中记录；发送器只读已提交 Outbox。
- Inbox 按 `(source_system, event_id)` 去重；同 ID 不同 payload hash 进入冲突隔离。
- 同一 idempotency key + 相同 payload 返回第一次结果；不同 payload 返回 409，零副作用。
- ERP 成功、MES 失败是 `PARTIALLY_APPLIED`，不能假装全局回滚。
- 已 `APPLIED` 的外部事实不能通过改内存变回未发生，只能创建补偿草稿或人工处置。
- 新订单、BOM版本、库存、供应承诺、产能、设备状态或审批状态变化命中计划依赖时，旧计划立刻 `STALE`。
- Outbox/Saga用于跨系统失败可观察和补偿，但不承诺分布式 ACID；主流架构同样要求消费者幂等。[29]

## 10. 可视化 SPEC

### 10.1 恢复指挥台布局

```text
┌────────────────────────────────────────────────────────────┐
│ 事件摘要 | ERP快照rev17 | MES快照rev12 | 证据冲突 | Live │
├───────────────────┬────────────────────────────────────────┤
│ 订单影响 DAG      │ 三方案 KPI                              │
│ 供应商→物料       │ 按时量 / 延期量 / 成本 / 应急 / 变更数 │
│ →产品→订单→产线   │                                        │
├───────────────────┴────────────────────────────────────────┤
│ 三方案同轴甘特：保交付 / 平衡 / 少变更                    │
├────────────────────────────────────────────────────────────┤
│ 方案变更明细 | 人工审批 | Outbox | ACK/Callback | 回流状态 │
└────────────────────────────────────────────────────────────┘
```

### 10.2 订单影响图

- 固定五层：`supplier/source → material → product → order → production_line`。
- 节点颜色：红=确定受影响，橙=风险，蓝=需人工确认，灰=未影响。
- 边必须来自 `ImpactReport.evidence_paths`，点击显示 source locator 与 hash；不允许 LLM 自由生成关系。
- 顶部显示：受影响订单 3 个、影响数量 217 台、关键物料 Q2J、关联产线 1 条。
- 使用分层 DAG，不用不能守恒的装饰性 Sankey。

### 10.3 三方案比较

- 三个甘特图使用完全相同 x 轴、订单顺序和颜色语义。
- KPI 同时显示绝对值与相对“当前计划”的变化。
- 资源调整至少包含：应急采购量、加班工序数、移动工序数、涉及订单数、恢复成本。
- 每个方案显示 solver status、verifier status、scenario hash 短码、plan hash 短码。
- 人审选择与正在查看的方案绑定；不能看 A 批 B。

### 10.4 集成状态

- `202 ACCEPTED`：黄色“已接收，等待执行结果”。
- `APPLIED`：绿色，显示外部对象 ID、source revision 和回调时间。
- `PARTIALLY_APPLIED`：红橙色，逐目标列出已发生、未发生和建议动作。
- `STALE`：红色遮罩旧甘特图，明确“禁止继续写出，需重新求解和审批”。
- 所有外部系统卡片固定显示 `SANDBOX · 非真实生产系统`。

## 11. Agent 参与边界

| 环节 | Agent/LLM | 确定性系统 | 人 |
|---|---|---|---|
| 事故理解 | 抽取候选、指出缺失/冲突、生成调查计划 | 实体白名单、span、schema | 确认冲突值 |
| 数据读取 | 选择 allowlisted ERP/MES read tool | adapter、mapping、freshness、hash | 无 |
| 影响分析 | 解释路径 | BOM/订单/库存/产能计算 | 无 |
| 恢复方案 | 解释权衡 | CP-SAT + verifier | 选择/批准 |
| 写回 | 不能构造厂商请求 | canonical command、policy gate、adapter mapping | 批准 |
| ACK/回流 | 可解释失败并提出处置选项 | 去重、状态机、Saga、stale invalidation | 决定补偿/重新审批 |

Agent 不持有厂商凭证；LLM 输出必须先进入 canonical schema，再经过 deterministic policy gate。OAuth2 client credentials 适用于机器身份，生产写连接可叠加 mTLS；秘密只允许来自环境/secret store，不进代码、ZIP或日志。[26]

## 12. 功能需求

| ID | MUST需求 | 验收 |
|---|---|---|
| FR-001 | 加载 ERP/MES canonical snapshots 并保留 source revision、raw hash、mapping version | 数据页可追踪每个实体来源 |
| FR-002 | adapter registry 显示能力与 sandbox 环境 | UI和JSON均可查 |
| FR-003 | Agent只能调用 allowlisted read/write-draft tools | 非法工具请求被拒绝并记录 |
| FR-004 | 生成确定性订单影响 DAG | 每条边可追溯到 impact evidence path |
| FR-005 | 三方案同屏甘特和 KPI | 同轴、同序、可复算 |
| FR-006 | 批准前禁止任何 outbound command | 返回 `HUMAN_APPROVAL_REQUIRED`，零 Outbox |
| FR-007 | 写出前重算并核验双 hash | 任一变化则 `STALE` |
| FR-008 | 批准后创建 ERP/MES canonical commands 和 Outbox | command 绑定 approval/hash |
| FR-009 | HTTP 沙箱返回 transport ACK 和异步 business callback | UI不混淆两类状态 |
| FR-010 | 相同 POST 重试不重复创建外部草稿 | duplicate=true且仅一个目标对象 |
| FR-011 | 支持 `APPLIED/PARTIALLY_APPLIED/REJECTED/TIMEOUT_UNKNOWN` | 每种状态有固定演练样例 |
| FR-012 | ERP/MES回流改变依赖时旧计划失效 | 未发命令取消，已发命令进入协调 |
| FR-013 | 失效后自动重算并重新等待审批 | 旧 approval 不能复用 |
| FR-014 | 全链路审计 | correlation→plan→approval→command→ACK→callback 可串联 |
| FR-015 | Replay与Live明确分离 | 无密钥仍可完整复现，Live另报 |
| FR-016 | 导出机器可读运行证据 | JSON包含时间、版本、hash、状态和失败 |

## 13. 非功能需求

| ID | 要求 |
|---|---|
| NFR-001 | Replay 主链路连续10次业务指标、plan hash、命令数完全一致 |
| NFR-002 | Live 端到端多轮会话10次，报告成功/澄清/安全停止率，不删除失败样例 |
| NFR-003 | 任意未授权外部写动作数量必须为0 |
| NFR-004 | 相同幂等键的业务副作用最多1次；审计可看到重复投递 |
| NFR-005 | 回调、重复、乱序、部分失败、超时、schema drift均有可见状态和恢复路径 |
| NFR-006 | Replay本地核心链路单次目标≤5秒；Live延迟只实测报告，不硬伪造 SLA |
| NFR-007 | 新环境按 README 启动 HTTP 沙箱和 Streamlit，无隐藏手工步骤 |
| NFR-008 | ZIP、Git仓库、日志、视频不含 API key、token、证书或个人/企业敏感信息 |
| NFR-009 | 公开数据、模拟数据、厂商文档、映射推断分层标识 |
| NFR-010 | 不增加真实设备控制能力；OPC UA/MQTT fixture 仅 Read/Subscribe/Replay [28] |

## 14. 对抗性验收

1. 无 approval 调用写工具：403，Outbox=0。
2. approval 绑定 plan A，却提交 plan B：拒绝。
3. 同一 command 网络超时后重试：外部草稿只能1份。
4. 同 idempotency key、不同 payload：409，零覆盖。
5. HTTP 202 后 UI 不得显示完成。
6. ERP applied、MES rejected：整体 `PARTIALLY_APPLIED`，展示人工/补偿建议。
7. MES callback 先 `APPLIED` 后到旧 `PENDING`：状态不得倒退。
8. 回调重复两次：领域状态更新一次，审计保留 duplicate。
9. MES产能 revision 变化：旧计划 stale，未发命令取消，重新求解。
10. 已 applied 的 ERP草稿遇到 stale：不能改内存假装回滚。
11. SFTP/CSV缺 manifest、checksum错、record count错：整个批次隔离。
12. 模型伪造 ACK JSON：作为不可信文本，不改变集成状态。
13. 模型请求 OPC UA Write/MethodCall：策略层阻断。
14. API 429/503：带相同 idempotency key 退避重试；超过上限进入 DLQ。
15. API 401/403/409/412/422：不得盲重试。
16. 回流造成全局无解：0新工单，明确最大可交付和缺口。

## 15. 评测与运行证据

新增 `artifacts/integration_validation_report.json`，包含：

- Git revision、runtime mode、model、adapter version、schema version；
- 10次 Replay 和10次 Live 完整会话逐次结果；
- 每次 scenario/plan/artifact hash；
- 工具调用、approval、command、ACK、callback、retry、DLQ；
- 端到端任务闭环率；
- 正确澄清率、安全停止率、未授权写动作数；
- 重复副作用数、stale 识别率、状态倒退数；
- p50/p95模型延迟、求解延迟、端到端延迟；
- 所有失败和限制，不只给平均分。

视频必须展示至少一次 Live；评委无密钥时可以 Replay 完整复现。现有 90 次模型黄金集评测保留，但与新增的端到端多轮稳定性分开报告。

## 16. 安全、数据与合规

- 所有 ERP/MES 业务数据均由 Mendeley 公开数据派生和确定性模拟，不使用阿里云内部或真实企业数据。
- `source_system`、UI 和日志均标注 sandbox；厂商名称只出现在市场/映射文档，不出现在“连接成功”假状态。
- 采购申请、排程变更始终是草稿，不能替代企业人员或真实系统审批。
- OT 数据只读，不控制设备，不给出现场安全操作命令。
- 日志脱敏，只记录 credential reference、请求/响应 hash、HTTP状态、错误码和外部模拟对象 ID。
- 开源仓库包含代码、schema、example、mapping、测试和许可证，不包含商业文档全文或厂商受限 schema。

## 17. 工程结构

建议新增：

```text
src/delivery_guard/integration/
  models.py            # canonical entity/command/ack/callback
  adapters.py          # adapter protocol and registry
  erp_sandbox.py       # ERP state and command handling
  mes_sandbox.py       # MES state and event replay
  outbox.py            # outbox/inbox/idempotency
  reconciliation.py    # partial failure/saga/stale handling
  server.py            # local HTTP sandbox
  visualization.py     # impact graph / comparison frames
contracts/
  openapi.yaml
  asyncapi.yaml
  schemas/*.schema.json
  examples/*.json
  mappings/*.yaml
data/integration_sandbox/
  erp_snapshot.json
  mes_snapshot.json
  callback_scenarios.json
tests/
  test_integration_contracts.py
  test_integration_adversary.py
  test_reconciliation.py
scripts/
  run_integration_validation.py
artifacts/
  integration_validation_report.json
docs/
  vendor_mapping.md
  integration_boundary.md
```

P0不引入 Kafka、MQTT broker、外部数据库或 Docker。协议行为由本地 HTTP 沙箱、文件 fixture 和持久化 JSON/SQLite 证据实现；若新增 SQLite，只使用 Python 标准库。

## 18. 交付物更新

| 材料 | 必须变化 |
|---|---|
| Streamlit Demo | 恢复指挥台 + 集成闭环页 + sandbox标签 |
| PPT/PDF | 新增市场/接口选择、三方案可视化、ERP/MES回流闭环、稳定性证据 |
| Demo视频 | 已重录 2 分 02 秒真实操作；展示 48 小时事故、真实模型、ERPNext→OpenMES 同号工单下发、合同异常回流与六步证据链；190 语速并烧录中文字幕 |
| README | 两命令启动、Replay/Live/HTTP模式、边界说明 |
| 架构与合规 | 加 ISA-95 L3/L4 边界、adapter/outbox/callback/stale |
| 代码ZIP | openapi/asyncapi/schema/example/mapping/test/evidence 全部包含 |
| 答辩稿 | 首句说明“协议级沙箱，不冒充生产连接”，随后展示端到端证据 |

## 19. 实施顺序与冻结点

| 日期 | 工作 | 冻结条件 |
|---|---|---|
| 8月29日 | SPEC、厂商/协议证据、范围冻结 | 确认P0两Profile和主Demo |
| 8月30日 | canonical contract、HTTP沙箱、Outbox/Callback | 核心接口测试通过 |
| 8月31日 | 指挥台、影响图、三甘特、回流重算 | 主链路可手动完成 |
| 9月1日 | 16项对抗测试、10×Replay、10×Live | 报告生成且无越权写 |
| 9月2日 | PPT/PDF、视频、README、ZIP、全新环境验收 | 交付物一致、可复现 |
| 9月3日12:00前 | 最终检查并提交 | 留6小时处理上传问题 |

## 20. 成功标准

复赛版被视为完成，必须同时满足：

1. 评委30秒内能看懂217台订单如何受影响以及三个方案差异。
2. 至少一条命令经历真实 HTTP `202 → callback → business result`。
3. 至少一次 ERP成功/MES失败，系统正确显示部分成功。
4. 至少一次 MES状态回流使旧计划失效并重新等待审批。
5. 任何无审批、旧 hash、伪造 ACK 或设备控制请求均为0副作用。
6. 10次 Replay 稳定，10次 Live 结果和失败完整披露。
7. 评委无厂商账号、无模型密钥也能用 Replay 完整运行。
8. 所有厂商表述为“官方接口调研/映射蓝图/协议 Profile”，不宣称认证或生产接入。

## 21. 反向审查与争议

### 争议一：协议沙箱是不是“假对接”

如果只有页面按钮和预制成功文案，就是假对接。本 SPEC 要求真实 HTTP 边界、序列化 schema、Outbox、幂等、transport ACK、business callback、失败/乱序/超时和机器可读日志，因此能证明对接机制；但它仍不能证明厂商生产互操作，必须明确这个限制。

### 争议二：为什么不做更多厂商

五个浅 mock 会让评委追问具体 endpoint、权限和错误语义时立即暴露。两个深 Profile + 六家映射蓝图更能证明可复用架构，并符合5%的开放/复用评分。

### 争议三：市占率是不是选型依据

不是。市占率只帮助评委理解代表性；最终选型还取决于目标客户、制造模式、部署版本、公开文档、tenant权限和项目时间。SPEC保留国产与国际两组代表，运行实现按协议模式而非厂商 Logo 组织。

### 争议四：收到消息是否等于完成闭环

不是。MQTT QoS或Kafka exactly-once只约束传输/消息写入，不能证明 ERP/MES 业务副作用恰好发生一次；HTTP 202也不代表执行完成。必须等待业务回调或状态查询，并以幂等和协调状态为准。[25][27][29]

### 争议五：回流后自动重算是否越权

重新分析和生成候选可以自动，批准和外部业务变更不能自动。回流使旧计划失效后，系统必须重新进入 `AWAITING_APPROVAL`。

## 22. 待讨论决策

建议直接冻结以下选择：

- D1：P0保留自有本地 HTTP 沙箱作为离线回退，同时接入真实 ERPNext 与 OpenMES 本机测试实例；任一实例未配置或验证失败时，UI必须分别显示降级状态，不得显示“真实系统已连接”。
- D2：底层只做 `erp_transaction_adapter` 与 `mes_operations_adapter`；可运行映射只做 `sap_s4_dm_contract_profile` 与 `kingdee_blacklake_contract_profile`。
- D3：主视频使用国产组合；SAP组合用于一键切换和国际适配证明；Oracle、D365、用友、Siemens、Rockwell、Apriso、Proficy、宝信、鼎捷进入扩展矩阵。
- D4：主 Demo 必须使用“ERP成功、MES失败→MES回流→旧计划失效→重新审批”链路。
- D5：三方案同屏甘特 + 订单影响 DAG 进入首页，不做装饰性多模态。
- D6：最终视频为 2 分 02 秒；线上答辩使用同一主链路的 5 分钟版本。

## 23. ERPNext 真实测试实例增量规范（2026-08-30）

### 23.1 目标与证据边界

真实接入只用于比赛测试数据，部署形态可以是本机自托管或 Frappe Cloud 试用租户。它证明的是本项目能对真实 ERPNext HTTP API 执行受限业务闭环，不外推为 SAP、金蝶、黑湖认证连接器，也不声称已经进入生产环境。

### 23.2 最小闭环

1. 服务端读取 ERPNext 当前用户与允许的业务对象，生成带时间和内容 hash 的真实快照。
2. 已完成 LangGraph 人审且 scenario/plan/approval hash 匹配时，创建 Material Request 与 Work Order 草稿。
3. 每次创建必须保存 ERPNext 返回的 doctype、name、creation、modified 和 docstatus，并立即 GET 回读验证。
4. 人工在 ERPNext 界面提交 Work Order、开始或完成 Job Card 后，Agent 轮询 Job Card/Work Order 的 modified、status、completed_qty 和实际工时。
5. 任何影响物料、数量、时间、产能或状态的变化都产生新的 source revision，使旧批准失效并重新求解；新工单数保持 0，直到再次人审。

### 23.3 安全约束

- 仅允许 `sandbox` / `test` 环境；生产环境配置直接拒绝启动。
- Base URL、API key、API secret 只从服务端读取，不写入仓库、浏览器或日志。
- 允许读取的 DocType：Sales Order、BOM、Bin、Work Order、Job Card、Material Request、Item、Supplier、Warehouse。
- 允许创建的 DocType：Material Request、Work Order，且 `docstatus=0`。
- 禁止 submit、cancel、delete、付款、库存过账、原生审核、设备写入和任意 RPC。
- API 错误、字段缺失、权限不足和回读不一致必须失败关闭，不得伪造成功记录。

### 23.4 验收标准

1. 假 ERPNext HTTP 服务上的契约测试覆盖认证头、URL编码、读取、草稿写入、回读、401/403/409/422/5xx、超时和敏感信息脱敏。
2. 未配置实例时健康检查返回 `not_configured`，原合同沙箱仍可复现，但两者标签不同。
3. 配置真实实例后，Demo 展示实际 base host、ERPNext 版本、真实单据 ID 和回读证据，不显示密钥。
4. 相同命令重试不得创建第二份草稿；同键不同 payload 失败关闭。
5. Work Order / Job Card revision 变化后，旧 approval 明确失效，新候选回到 `awaiting_approval`。

## 参考资料

[1] GOAI 2026组委会. 赛道二复赛规则. 2026-08-29. https://geekbang.feishu.cn/wiki/Iz87wzitGipFmHkpXlqc8L3cntg
[2] GOAI 2026组委会. 《有界》定向优化建议邮件. 2026-08-29. 用户提供。
[3] 中国信息通信研究院. 中国企业级 SaaS 产业发展研究报告（2024年）. https://www.caict.ac.cn/kxyj/qwfb/ztbg/202408/P020240815374016912879.pdf
[4] 中国信息通信研究院. 专精特新中小企业数字化转型研究报告（2024年）. https://www.caict.ac.cn/kxyj/qwfb/bps/202501/P020250124516764358220.pdf
[5] Gartner. Magic Quadrant for Cloud ERP for Product-Centric Enterprises. 2024-11. https://www.gartner.com/en/documents/5910375
[6] SAP. S/4HANA Cloud APIs for Sales. https://help.sap.com/docs/SAP_S4HANA_CLOUD/a376cd9ea00d476b96f18dea1247e6a5/055923d19aeb49eca0a572db54105fa4.html
[7] SAP. S/4HANA Cloud BAPIs and IDocs. https://help.sap.com/docs/SAP_S4HANA_CLOUD/0f69f8fb28ac4bf48d2b57b9637e81fa/2cf48091d5864284ac4541b86a8737fd.html
[8] Oracle. Fusion Cloud SCM File-Based Data Import. https://docs.oracle.com/en/cloud/saas/supply-chain-and-manufacturing/26b/faips/file-based-data-import.html
[9] Microsoft. Dynamics 365 Finance and Operations OData. https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/data-entities/odata
[10] Microsoft. Dynamics 365 Finance and Operations Data Events. https://learn.microsoft.com/en-us/dynamics365/fin-ops-core/dev-itpro/business-events/data-events
[11] 用友. 开发者中心 OpenAPI. https://developer.yonyou.com/openAPI
[12] 金蝶. 金蝶云苍穹 OpenAPI. https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29
[13] Gartner. Market Guide for Manufacturing Execution Systems. 2026-03. https://www.gartner.com/en/documents/7617465
[14] 2026中国生产制造工业软件行业洞察报告. 2026-02. https://pdf.dfcfw.com/pdf/H3_AP202602281820132908_1.pdf?1772277139000.pdf=
[15] Siemens. OT to MES Integration with Industrial Edge and Opcenter. https://www.siemens.com/th-th/content/architecture-hub/op-center/
[16] SAP. Digital Manufacturing Service Catalog APIs. https://help.sap.com/docs/sap-digital-manufacturing/service-catalog/apis
[17] Rockwell Automation/Plex. ERP Custom APIs. https://plex.rockwellautomation.com/en-us/resources/10301-plex-datasheet-e-r-p-custom-a-p-is.html
[18] Dassault Systèmes. DELMIA Apriso System Integration. https://www.3ds.com/products/delmia/apriso/system-integration
[19] GE Vernova. Proficy Smart Factory Integration Methods. https://www.gevernova.com/software/industry/automotive?tabIndex=2
[20] 黑湖科技. Black Lake Manufacturing 3.0 Open API. https://v3-hw-openapi.blacklake.cn/document/api?detailId=1686645473258363&url=%2Fmed%2Fopen%2Fv2%2Fwork_order%2F_doimport
[21] ISA. ISA-95 Series of Standards. https://www.isa.org/standards-and-publications/isa-standards/isa-95-standard
[22] OASIS. OData Version 4.01 Part 1 Protocol. https://docs.oasis-open.org/odata/odata/v4.01/os/part1-protocol/odata-v4.01-os-part1-protocol.html
[23] OpenAPI Initiative. OpenAPI Specification 3.2.0. https://spec.openapis.org/oas/latest.html
[24] AsyncAPI Initiative. AsyncAPI Specification 3.1.0. https://www.asyncapi.com/docs/reference/specification/latest
[25] CNCF. CloudEvents Specification 1.0. https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md
[26] IETF. RFC 8705 OAuth 2.0 Mutual-TLS Client Authentication. https://datatracker.ietf.org/doc/html/rfc8705
[27] IETF. RFC 9110 HTTP Semantics. https://datatracker.ietf.org/doc/html/rfc9110
[28] OPC Foundation. OPC UA Part 1 Overview and Concepts. https://reference.opcfoundation.org/specs/OPC-10000-1/4
[29] AWS. Prescriptive Guidance: Cloud Design Patterns. https://docs.aws.amazon.com/pdfs/prescriptive-guidance/latest/cloud-design-patterns/cloud-design-patterns.pdf
