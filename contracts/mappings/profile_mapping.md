# ERP/MES 合同映射与落地边界

两个 profile 共享同一项目自有 canonical contract；差异只在适配器层。当前均为可运行沙箱映射，不是厂商认证连接器，也未连接真实租户。

官方依据核对日期：2026-08-29。

## 厂商官方协议依据

- SAP S/4HANA ERP：官方 Purchase Requisition API 暴露 `A_PurchaseRequisitionHeader`；Purchase Order API 使用 OData V4，支持创建、读取、更新与删除等操作。
  - [SAP Purchase Requisition API](https://help.sap.com/docs/SAP_S4HANA_CLOUD/bb9f1469daf04bd894ab2167f8132a1a/2905455816dda007e10000000a441470.html)
  - [SAP Purchase Order OData V4](https://help.sap.com/docs/SAP_S4HANA_CLOUD/0e602d466b99490187fcbb30d1dc897c/c89eec80ec2043d980cb7b8c89e0a00a.html)
- SAP Digital Manufacturing MES/MOM：官方提供 OData 与 REST API；API 集成通过 service key 获得 public API endpoint，并使用 OAuth 2.0 client credentials。
  - [SAP Digital Manufacturing APIs](https://help.sap.com/docs/sap-digital-manufacturing/apis/apis-for-sap-digital-manufacturing)
  - [SAP API Integration and OAuth 2.0](https://help.sap.com/docs/sap-digital-manufacturing/operations-guide/prepare-for-api-integration?ai=true)
- 金蝶云苍穹 / 星瀚风格 ERP：官方开放平台说明 RESTful OpenAPI、JSON、GET/POST/PUT/PATCH/DELETE、Token 认证，以及保存、提交、审核等业务操作 API 和开放事件。
  - [金蝶官方 OpenAPI 说明](https://developer.kingdee.com/knowledge/specialDetail/226337046514476288?lang=zh-CN&productLineId=29)
- 黑湖智造 3.0 MES：官方提供 Open 接口平台；工单导入接口的公开示例路径为 `/med/open/v2/work_order/_doimport`。接口字段和认证方式仍须以客户租户与具体 API detailId 为准。
  - [黑湖智造 3.0 Open 接口平台](https://v3-hw-openapi.blacklake.cn/release)
  - [黑湖官方工单接口示例](https://v3-hw-openapi.blacklake.cn/document/api?detailId=1686645473258363&url=%2Fmed%2Fopen%2Fv2%2Fwork_order%2F_doimport)

以上官方资料证明的是厂商存在这些协议和业务对象，不证明本项目已经取得真实租户授权或通过厂商认证。Demo 证明的是 canonical contract、HTTP 202/异步 callback、幂等、审批绑定、状态回流与异常重算的可运行实现。

| Canonical 对象/动作 | SAP S/4HANA + SAP Digital Manufacturing | 金蝶云星空 + 黑湖智造 | Demo 中的证明 |
|---|---|---|---|
| 订单、BOM、库存、采购申请草稿 | S/4HANA OData/REST business objects；生产化以已开通 API 与权限为准 | 金蝶 WebAPI/OpenAPI；生产化按数据中心/API 认证配置 | `GET /sandbox/v1/erp/snapshots/{id}`；ERP command/callback |
| 产线、工艺路线、排程变更草稿 | SAP DM public APIs/event integration；S/4 与 DM 由标准集成内容或客户集成层衔接 | 黑湖 OpenAPI/集成平台；与金蝶通过客户集成层映射 | `GET /sandbox/v1/mes/snapshots/{id}`；MES command/callback |
| 异步执行状态 | webhook/event/polling adapter 映射为 canonical callback | webhook/event/polling adapter 映射为 canonical callback | `POST /youjie/v1/callbacks` |
| 幂等与并发 | 项目 outbox/inbox + vendor record/version key | 项目 outbox/inbox + vendor record/version key | idempotency key、source revision、sequence |
| 审批 | 仅提交草稿或本地人审；不得伪造原生审批 | 仅提交草稿或本地人审；不得伪造原生审批 | approval/scenario/plan hash 三重绑定 |
| 设备控制 | 禁止 OPC UA write、PLC write、method call | 禁止设备写入或现场控制 | schema validator + ADV-13 |

生产化最小替换面只有 adapter：认证、字段映射、分页/限流、原生错误码、回调或轮询、租户级权限。LangGraph、canonical contract、求解器、验证器、审批失效规则和审计语义不随厂商改变。
