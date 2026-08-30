# 周末线上答辩 Runbook

## 核心原则

主展示只走一条链：供应延迟→三方案→批准→真实 ERPNext 草稿写入/回读→独立 ERP/MES 部分失败→旧计划失效→重新等待审批。来源冲突、全局无解、提示注入只在评委追问时展开。现场不运行 90 次模型评测，也不把临时本机端口当在线地址。

## 30 分钟前

1. 接电源，关闭系统升级、代理自动切换和无关通知。
2. 打开 PPT/PDF、Demo、视频、证据 JSON，全部使用本地文件。
3. 启动 Replay 备用实例；若 Live key/endpoint 正常，再启动 Live 实例。
4. 执行 `pytest -q` 和 `run_integration_validation.py --runs 2` 快速烟测。
5. 浏览器缩放 90%–100%，确认甘特图、影响图、ERP/MES tab 无横向遮挡。
6. 麦克风、共享屏幕、系统声音、备用热点各检查一次。

## 5 分钟主陈述

| 时间 | 内容 | 必须出现的证据 |
|---|---|---|
| 0:00–0:35 | 用户/问题/边界 | 制造计划员；决策辅助；不控制设备 |
| 0:35–1:10 | 数据与 Agent 分工 | Mendeley 217 行；Live/Replay 区分；LLM 不做数值决策 |
| 1:10–2:20 | 影响图和三方案 | 订单影响传播、同轴甘特、交付/成本/资源差异 |
| 2:20–2:50 | 人工审批 | interrupt；approval/scenario/plan hash；只生成草稿 |
| 2:50–3:25 | 真实 ERPNext | 4 张新增草稿 ID + 1 条既有供应承诺引用；docstatus=0；GET 回读；限定单据 revision 变化 |
| 3:25–4:20 | 独立 ERP/MES 回流 | HTTP 202=PENDING；ERP APPLIED；MES REJECTED；PARTIALLY_APPLIED |
| 4:20–4:45 | 反馈再规划 | MES产能变更；旧批准失效；0新工单；等待新批准 |
| 4:45–5:00 | 验证与落地 | ERPNext→OpenMES 真实同号工单与状态回流 + 当前 72/72、四种集成 profile×10；生产边界 |

## 故障切换

| 故障 | 10 秒内动作 | 口径 |
|---|---|---|
| Live 模型超时/限流 | 切 Replay，随后打开已生成 live report | “Replay 用于可复现演示，真实 90 次调用证据单独留存。” |
| Streamlit 崩溃 | 播放 `youjie_semifinal_demo.mp4` | “这是同版本真实操作录屏；代码和运行证据在附件。” |
| 网络/会议卡顿 | 切本地 PDF，再口述 JSON 结果 | 不现场下载、不登录云平台 |
| 求解器耗时波动 | 使用预置批准结果/视频 | 不声称固定毫秒级性能 |
| 评委质疑厂商接入 | 打开 OpenAPI、profile mapping 和 202/callback 状态 | 先承认沙箱，再解释生产 adapter 替换面 |

## 禁止口径

- “已经接入 SAP/金蝶/黑湖生产系统”——没有真实 tenant，也未认证。
- “HTTP 202 就执行成功”——202 只有传输接收。
- “真实工厂验证提升 X%”——没有授权企业历史基线。
- “AI 自动批准/自动控制产线”——审批在人，设备控制禁止。
- “大模型准确率 100%”——只能陈述特定黄金集和约束后的合同通过率。
- “替代 ERP/MES/APS”——定位是它们上方的异常决策与验证层。

## 随手可开的文件顺序

1. `docs/youjie_goai_semifinal_pitch.pdf`
2. 本地 Streamlit Demo
3. `docs/youjie_semifinal_demo.mp4`
4. `artifacts/integration_validation_report.json`
5. `contracts/openapi.yaml`
6. `docs/defense_qa.md`
