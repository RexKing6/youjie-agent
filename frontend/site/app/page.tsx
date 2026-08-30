'use client';

import { useMemo, useState } from 'react';
import {
  AlertTriangle, ArrowLeft, ArrowRight, BadgeCheck, Boxes, Check,
  CircleDollarSign, Clock3, Database, Factory, FileCheck2, GitBranch,
  PackageCheck, RotateCcw, ShieldCheck, UserCheck, X, Zap,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress, ProgressLabel, ProgressValue } from '@/components/ui/progress';
import { LiveAgentWorkbench } from '@/components/live-agent-workbench';

type Plan = {
  name: string;
  tone: 'cyan' | 'violet' | 'slate';
  onTime: number;
  late: number;
  emergency: number;
  cost: number;
  workOrders: number;
  message: string;
  budget: number;
  rawLateUnitHours: number;
  priorityRisk: number;
  maxLate: number;
  orders: Array<{
    id: string;
    customer: string;
    priority: '关键' | '高' | '普通';
    units: number;
    due: number;
    start: number;
    completion: number;
    late: number;
  }>;
};

const plans: Plan[] = [
  {
    name: '保交付', tone: 'cyan', onTime: 91, late: 126, emergency: 91, cost: 728, budget: 800,
    rawLateUnitHours: 8244, priorityRisk: 8244, maxLate: 32, workOrders: 5,
    message: '花 728 元加急 91 件，保住 91 台关键订单；其余两单分别晚 28 / 32 小时。',
    orders: [
      { id: 'ORD-01', customer: '华东旗舰经销网络（模拟）', priority: '关键', units: 91, due: 24, start: 16, completion: 20, late: 0 },
      { id: 'ORD-02', customer: '区域车队客户（模拟）', priority: '高', units: 81, due: 24, start: 48, completion: 52, late: 28 },
      { id: 'ORD-03', customer: '直营网点补货（模拟）', priority: '普通', units: 45, due: 24, start: 52, completion: 56, late: 32 },
    ],
  },
  {
    name: '平衡（预算受限）', tone: 'violet', onTime: 45, late: 172, emergency: 45, cost: 360, budget: 400,
    rawLateUnitHours: 5140, priorityRisk: 20516, maxLate: 32, workOrders: 5,
    message: '预算只够 45 件且订单不可拆分，因此救下 45 台补货单；91 台关键单仍晚 28 小时。',
    orders: [
      { id: 'ORD-01', customer: '华东旗舰经销网络（模拟）', priority: '关键', units: 91, due: 24, start: 48, completion: 52, late: 28 },
      { id: 'ORD-02', customer: '区域车队客户（模拟）', priority: '高', units: 81, due: 24, start: 52, completion: 56, late: 32 },
      { id: 'ORD-03', customer: '直营网点补货（模拟）', priority: '普通', units: 45, due: 24, start: 16, completion: 20, late: 0 },
    ],
  },
  {
    name: '少变更', tone: 'slate', onTime: 0, late: 217, emergency: 0, cost: 0, budget: 0,
    rawLateUnitHours: 6760, priorityRisk: 22136, maxLate: 36, workOrders: 0,
    message: '不追加应急采购；三张订单分别延期 28 / 32 / 36 小时。',
    orders: [
      { id: 'ORD-01', customer: '华东旗舰经销网络（模拟）', priority: '关键', units: 91, due: 24, start: 48, completion: 52, late: 28 },
      { id: 'ORD-02', customer: '区域车队客户（模拟）', priority: '高', units: 81, due: 24, start: 52, completion: 56, late: 32 },
      { id: 'ORD-03', customer: '直营网点补货（模拟）', priority: '普通', units: 45, due: 24, start: 56, completion: 60, late: 36 },
    ],
  },
];

const steps = ['收到异常', '算清影响', '比较方案', '人工批准', '系统回流', '失效重算'];

const evidenceByStep = [
  { title: '真实数据与模拟覆盖层分开标注', items: ['公开数据原始需求行：217', '事故邮件：模拟，延迟 48 小时', '模型只提取事实和原文位置'], capability: '在线模型与资料理解', explanation: '需求、BOM、库存和产能来自可追溯公开行；事故邮件、价格、客户名和审批属于明确标注的模拟覆盖层。' },
  { title: '影响关系来自确定性数据', items: ['BOM：座椅 Q2J 是三款车的共同物料', '订单：91 + 81 + 45 = 217 台', 'LLM 无权添加订单或产线关系'], capability: '订单影响图', explanation: '边来自 BOM、订单、物料和产线主数据；LLM 只识别异常，不新增业务关系。' },
  { title: '每张订单和总账都能对上', items: ['逐单展示截止、完成与延期小时', '成本 / 延期量 / 优先级风险同屏比较', 'CP-SAT 后由独立 verifier 重放硬约束'], capability: '方案可视化与求解验证', explanation: 'CP-SAT 是可替换求解器；有界补齐异常文本、跨系统事实、候选求解、人审门禁、执行回流和失效重算之间的可追溯闭环。' },
  { title: '批准绑定具体版本', items: ['审批人：demo_planner', '绑定 scenario hash + plan hash', '批准前外发命令数：0'], capability: '人工确认与安全边界', explanation: '审批同时绑定人、场景 hash 和计划 hash；任一事实变化，旧批准都不能再用。' },
  { title: 'HTTP 202 不等于业务成功', items: ['ERP：APPLIED，生成草稿编号', 'MES：REJECTED，产能版本已变化', '全局状态：PARTIALLY_APPLIED'], capability: 'ERP / MES 执行回流', explanation: '真实 ERPNext 与 OpenMES 用于本机开源测试；商业厂商路径是协议兼容沙箱，生产接入仍需租户授权与字段映射。' },
  { title: '旧批准不能偷渡到新事实', items: ['对抗演练：注入新增停线 48–68h', 'MES revision：12 → 13，旧 approval_006 失效', '重算后工单：0，等待重新批准'], capability: '异常重算与多轮稳定性', explanation: '这里模拟 MES 回告新增停线；真实场景中的变化可来自故障、维修超时、质量返工、插单、人员或物料状态更新。' },
];

function FactTag({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' }) {
  return <span className={`fact-tag fact-${tone}`}>{children}</span>;
}

function ScenarioHeader() {
  return (
    <div className="case-strip">
      <div className="case-id"><span>CASE 01</span><strong>汽车座椅供应延迟</strong></div>
      <div className="case-facts" aria-label="案例核心数字">
        <div><span>订单总量</span><strong>217 台</strong></div>
        <div><span>关键物料</span><strong>座椅 Q2J</strong></div>
        <div><span>确认延迟</span><strong className="danger-text">48 小时</strong></div>
      </div>
      <Badge variant="outline" className="boundary-badge"><ShieldCheck /> 决策辅助 · 不控制设备</Badge>
    </div>
  );
}

function IncidentStep() {
  return (
    <div className="scene-grid incident-scene">
      <Card className="mail-card">
        <CardHeader>
          <div className="icon-chip coral"><AlertTriangle /></div>
          <CardTitle>供应商邮件说了什么？</CardTitle>
          <CardDescription>模拟邮件 · 2026-08-29 09:10</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mail-subject">Q2J 座椅供应中断</div>
          <p>“原供应商无法正常发运，预计恢复需要 <mark>48 小时</mark>。”</p>
          <div className="source-span">原文 span：字符 23–28 · 文件 hash 已记录</div>
        </CardContent>
      </Card>
      <div className="explain-stack">
        {[
          ['大模型只做阅读理解', '把“谁、什么物料、延迟多久”转成候选字段。'],
          ['规则检查实体是否存在', 'Q2J 必须能在已知物料清单中找到，否则停下来问人。'],
          ['此时还没有排程或工单', '模型不能自己宣布“有解”，更不能直接采购。'],
        ].map((item, index) => (
          <div className="plain-callout" key={item[0]}><span className="callout-number">{index + 1}</span><div><strong>{item[0]}</strong><p>{item[1]}</p></div></div>
        ))}
      </div>
    </div>
  );
}

function ImpactStep() {
  const nodes = [
    { type: '供应商', value: '原供应商', icon: Factory, tone: 'coral' },
    { type: '关键物料', value: '座椅 Q2J', icon: Boxes, tone: 'amber' },
    { type: '受影响车型', value: '三款车型', icon: GitBranch, tone: 'cyan' },
    { type: '客户订单', value: '91 + 81 + 45', icon: PackageCheck, tone: 'blue' },
    { type: '装配资源', value: '整车装配线', icon: Factory, tone: 'green' },
  ];
  return (
    <div className="impact-wrap">
      <div className="impact-chain" aria-label="供应商经过物料、车型和订单影响整车装配线">
        {nodes.map((node, index) => {
          const Icon = node.icon;
          return <div className="impact-segment" key={node.type}><div className={`impact-node ${node.tone}`}><Icon /><span>{node.type}</span><strong>{node.value}</strong></div>{index < nodes.length - 1 && <ArrowRight className="impact-arrow" aria-hidden="true" />}</div>;
        })}
      </div>
      <div className="impact-summary"><div><strong>217</strong><span>台都依赖 Q2J</span></div><div><strong>3</strong><span>张订单受影响</span></div><div><strong>0</strong><span>LLM 推测关系</span></div></div>
      <p className="judge-sentence"><strong>业务含义：</strong>不是“座椅晚两天”这么简单，而是必须立刻算出哪三张订单、多少台车、哪条线会被拖累。</p>
    </div>
  );
}

function PlanCard({ plan, selected, onSelect }: { plan: Plan; selected: boolean; onSelect: () => void }) {
  return (
    <button className={`plan-card ${plan.tone} ${selected ? 'selected' : ''}`} onClick={onSelect} aria-pressed={selected}>
      <div className="plan-card-head"><span>{plan.name}</span>{selected ? <BadgeCheck /> : <span className="select-dot" />}</div>
      <div className="plan-policy">预算上限 ¥{plan.budget} · 整单交付，不可拆分</div>
      <p>{plan.message}</p>
      <div className="delivery-bar" aria-label={`${plan.onTime} 台按时，${plan.late} 台延期`}><span className="on-time" style={{ width: `${(plan.onTime / 217) * 100}%` }} /><span className="late" style={{ width: `${(plan.late / 217) * 100}%` }} /></div>
      <div className="delivery-labels"><span>{plan.onTime} 按时</span><span>{plan.late} 延期</span></div>
      <div className="plan-metrics"><div><Boxes /><span>加急件</span><strong>{plan.emergency}</strong></div><div><CircleDollarSign /><span>增量成本</span><strong>¥{plan.cost}</strong></div><div><Clock3 /><span>最晚延期</span><strong>{plan.maxLate}h</strong></div></div>
    </button>
  );
}

function PlanStep({ selectedPlan, setSelectedPlan }: { selectedPlan: number; setSelectedPlan: (index: number) => void }) {
  const plan = plans[selectedPlan];
  const axisMax = 60;
  return (
    <div className="plans-scene">
      <details className="planning-primer" open>
        <summary>先分清 ERP、MPS、APS、MES 和 CP-SAT</summary>
        <div className="planning-primer-grid">
          <div><b>ERP</b><strong>Enterprise Resource Planning</strong><p>企业资源计划：管订单、采购、库存、成本等“公司账本和业务流程”。</p></div>
          <div><b>MPS</b><strong>Master Production Schedule</strong><p>主生产计划：决定未来要生产哪些成品、多少、何时完成；通常就是 ERP / 计划系统里的一个模块或方法。</p></div>
          <div><b>APS</b><strong>Advanced Planning &amp; Scheduling</strong><p>高级计划与排程：在有限物料、机器和产能下做更细的优化。成熟 ERP 也可能内置或配套 APS。</p></div>
          <div><b>MES</b><strong>Manufacturing Execution System</strong><p>制造执行系统：接收计划，管现场工单、报工、设备/产线状态和实际执行结果。</p></div>
          <div><b>CP-SAT</b><strong>当前 Demo 的可替换求解器</strong><p>Google OR-Tools 的通用约束求解内核。不是 ERP，也不是本项目独有创新；这里用它算候选计划。</p></div>
        </div>
        <div className="primer-links">
          <a href="https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f340785101c548c9beeda9284efd18a0/6e50c353b677b44ce10000000a174cb4.html" target="_blank" rel="noreferrer">SAP 官方：MPS</a>
          <a href="https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/f899ce30af9044299d573ea30b533f1c/4534c95360267614e10000000a174cb4-1541.html" target="_blank" rel="noreferrer">SAP 官方：PP/DS</a>
          <a href="https://developers.google.com/optimization/cp" target="_blank" rel="noreferrer">Google 官方：CP-SAT</a>
        </div>
      </details>
      <div className="plan-grid">{plans.map((plan, index) => <PlanCard key={plan.name} plan={plan} selected={selectedPlan === index} onSelect={() => setSelectedPlan(index)} />)}</div>
      <section className="decision-ledger" aria-label="三种恢复方案总账">
        <div className="section-title"><div><CircleDollarSign /><strong>先看总账：成本换回多少交付</strong></div><span>全部数字来自当前求解产物</span></div>
        <div className="decision-table-wrap"><table className="decision-table">
          <thead><tr><th>方案</th><th>增量成本</th><th>按时 / 延期</th><th>延期台时</th><th>优先级风险分</th><th>最晚延期</th></tr></thead>
          <tbody>{plans.map((item, index) => <tr key={item.name} className={selectedPlan === index ? 'active' : ''}>
            <th>{item.name}</th><td>¥{item.cost}</td><td>{item.onTime} / {item.late} 台</td><td>{item.rawLateUnitHours.toLocaleString()}</td><td>{item.priorityRisk.toLocaleString()}</td><td>{item.maxLate}h</td>
          </tr>)}</tbody>
        </table></div>
        <div className="tradeoff-chart" aria-label="成本与延期量对比图">
          {plans.map((item, index) => <button key={item.name} className={selectedPlan === index ? 'active' : ''} onClick={() => setSelectedPlan(index)}>
            <strong>{item.name}</strong>
            <div><span>成本</span><i className={`tradeoff-cost ${item.tone}`} style={{ width: `${Math.max(2, (item.cost / 800) * 100)}%` }} /><b>¥{item.cost}</b></div>
            <div><span>延期</span><i className="tradeoff-late" style={{ width: `${(item.late / 217) * 100}%` }} /><b>{item.late} 台</b></div>
          </button>)}
        </div>
        <p className="metric-note"><b>怎么看：</b>“延期台时”= 每张订单延期小时 × 台数；“优先级风险分”再乘关键/高/普通权重 5/3/1。它不是金额，而是让关键订单延期更痛的比较尺。场景中的 50/30/10 模拟延期损失字段尚未直接进入目标函数，所以这里不伪造“总财务收益”；最终选择仍由人决定。</p>
      </section>
      <section className="order-timeline" aria-label={`${plan.name}逐单排程`}>
        <div className="section-title"><div><Clock3 /><strong>{plan.name}：每张订单到底晚多久</strong></div><span>共同截止 h24 · 时间单位为事故发生后的小时</span></div>
        <div className="timeline-axis"><span>0h</span><span>12h</span><span className="due-axis">24h 截止</span><span>36h</span><span>48h</span><span>60h</span></div>
        {plan.orders.map((order) => <div className="timeline-row" key={order.id}>
          <div className="timeline-label"><strong>{order.id} · {order.units} 台</strong><span>{order.customer} · {order.priority}优先级</span></div>
          <div className="timeline-track">
            <i className="deadline-line" style={{ left: `${(order.due / axisMax) * 100}%` }} />
            {order.late > 0 && <i className="late-zone" style={{ left: `${(order.due / axisMax) * 100}%`, width: `${(order.late / axisMax) * 100}%` }} />}
            <i className={`production-block ${plan.tone}`} style={{ left: `${(order.start / axisMax) * 100}%`, width: `${((order.completion - order.start) / axisMax) * 100}%` }} />
          </div>
          <div className={`timeline-result ${order.late ? 'late' : 'on-time'}`}><strong>完成 h{order.completion}</strong><span>{order.late ? `延期 ${order.late}h` : '提前 4h'}</span></div>
        </div>)}
        <div className="timeline-legend"><span><i className={`legend-production ${plan.tone}`} />实际生产 4h</span><span><i className="legend-delay" />超过截止后的等待</span><span><i className="legend-deadline" />交付截止 h24</span></div>
        <div className="selected-rationale"><BadgeCheck /><p><b>这套方案做了什么：</b>{plan.message} 应急件指从备用供应商加急采购的同规格座椅，模拟增量价为 8 元/件，不是真实厂商报价。</p></div>
      </section>
    </div>
  );
}

function ApprovalStep({ selectedPlan, approved, setApproved }: { selectedPlan: number; approved: boolean; setApproved: (value: boolean) => void }) {
  const plan = plans[selectedPlan];
  return (
    <div className="approval-scene">
      <Card className="approval-card">
        <CardHeader><div className="icon-chip violet"><UserCheck /></div><CardTitle>系统停下来，等人负责</CardTitle><CardDescription>LangGraph interrupt · 不能自动越过</CardDescription></CardHeader>
        <CardContent>
          <div className="approval-row"><span>待批准方案</span><strong>{plan.name}</strong></div><div className="approval-row"><span>审批人</span><strong>demo_planner</strong></div>
          <div className="approval-row code-row"><span>场景版本</span><code>4f24d380724e2280…</code></div><div className="approval-row code-row"><span>计划版本</span><code>c0c23956a37f1b6e…</code></div>
          <Button size="lg" className="approve-button" onClick={() => setApproved(true)} disabled={approved}>{approved ? <><Check /> 已批准：只允许生成草稿</> : <><UserCheck /> 我是计划员，批准这个方案</>}</Button>
        </CardContent>
      </Card>
      <div className="gate-visual"><div className={`gate-state ${approved ? 'passed' : ''}`}><span>{approved ? <Check /> : <ShieldCheck />}</span><strong>{approved ? '哈希复核通过' : '审批门关闭'}</strong><p>{approved ? `生成 ${plan.workOrders} 张 draft_only 工单` : '外发命令 0 · 工单 0'}</p></div><div className="boundary-note"><AlertTriangle /><p><strong>注意：</strong>批准的是“把草稿交给业务系统”，不是替 ERP 完成组织审批，更不是控制设备。</p></div></div>
    </div>
  );
}

function FeedbackStep() {
  return (
    <div className="feedback-scene">
      <div className="transport-explainer">
        <div className="transport-step"><span>1</span><strong>HTTP 202</strong><p>对方收到了请求</p><FactTag tone="warn">仍是 PENDING</FactTag></div><ArrowRight />
        <div className="transport-step"><span>2</span><strong>业务回调</strong><p>真正执行结果回来</p><FactTag>按 operation ID 对账</FactTag></div><ArrowRight />
        <div className="transport-step result"><span>3</span><strong>部分应用</strong><p>不能假装全成功</p><FactTag tone="bad">PARTIALLY_APPLIED</FactTag></div>
      </div>
      <div className="system-results">
        <Card className="system-card success-system"><CardHeader><Database /><CardTitle>ERP 沙箱</CardTitle><Badge className="status-good">APPLIED</Badge></CardHeader><CardContent><p>采购/订单风险草稿已创建</p><code>PR-SANDBOX-00017</code><div className="system-foot"><Check /> 已发生事实，不能在本地假装回滚</div></CardContent></Card>
        <Card className="system-card error-system"><CardHeader><Factory /><CardTitle>MES 沙箱</CardTitle><Badge variant="destructive">REJECTED</Badge></CardHeader><CardContent><p>排程草稿被拒绝</p><code>STALE_CAPACITY_REVISION</code><div className="system-foot"><X /> 产线版本已从 rev-12 变化</div></CardContent></Card>
      </div>
      <p className="judge-sentence"><strong>业务含义：</strong>快递员说“包裹收到了”，不等于仓库已经入库；HTTP 202 和业务成功也是同一个道理。</p>
    </div>
  );
}

function ReplanStep() {
  return (
    <div className="replan-scene">
      <div className="replan-disclosure"><AlertTriangle /><p><b>先说清楚：</b>这里不是接到真实工厂传感器。合同沙箱主动注入“装配线在 h48–h68 新增停线”的对抗事件，用来证明状态变化后旧审批会失效。真实工厂里的同类变化可能来自设备故障、维修超时、质量返工、紧急插单、人员缺勤或物料实到时间变化。</p></div>
      <div className="replan-flow"><div className="revision-card old"><span>提交计划时看到的旧事实</span><strong>MES rev-12</strong><code>scenario 4f24…</code></div><ArrowRight /><div className="revision-event"><Zap /><strong>演练回调：新增停线 48–68h</strong><span>capacity:line_zp7_public</span></div><ArrowRight /><div className="revision-card new"><span>回流后的新事实</span><strong>MES rev-13</strong><code>scenario 2c3e…</code></div></div>
      <div className="invalidation-panel"><div className="invalid-stamp"><X /><span>approval_006</span><strong>已失效</strong></div><div className="replan-actions"><div><RotateCcw /><span>重新运行 CP-SAT + verifier</span><FactTag tone="good">3 个新候选均通过验证</FactTag></div><div><UserCheck /><span>重新等待人工批准</span><FactTag tone="warn">awaiting_approval</FactTag></div><div><FileCheck2 /><span>新工单保持为零</span><FactTag tone="good">0 work orders</FactTag></div></div></div>
      <div className="final-claim"><ShieldCheck /><div><strong>真正的“有界”</strong><p>Agent 可以读、算、比较、解释和重新规划；但新事实出现后，它不能拿旧批准继续执行。</p></div></div>
    </div>
  );
}

export default function Home() {
  const [step, setStep] = useState(0);
  const [selectedPlan, setSelectedPlan] = useState(1);
  const [approved, setApproved] = useState(false);
  const currentEvidence = evidenceByStep[step];
  const progress = ((step + 1) / steps.length) * 100;
  const scene = useMemo(() => {
    if (step === 0) return <IncidentStep />;
    if (step === 1) return <ImpactStep />;
    if (step === 2) return <PlanStep selectedPlan={selectedPlan} setSelectedPlan={setSelectedPlan} />;
    if (step === 3) return <ApprovalStep selectedPlan={selectedPlan} approved={approved} setApproved={setApproved} />;
    if (step === 4) return <FeedbackStep />;
    return <ReplanStep />;
  }, [step, selectedPlan, approved]);

  function focusWalkthrough() {
    window.requestAnimationFrame(() => {
      document.querySelector('.stepper')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function goPrevious() {
    setStep((value) => Math.max(0, value - 1));
    focusWalkthrough();
  }

  function goNext() {
    if (step === 3 && !approved) return;
    setStep((value) => Math.min(steps.length - 1, value + 1));
    focusWalkthrough();
  }

  function reset() {
    setStep(0);
    setSelectedPlan(1);
    setApproved(false);
    focusWalkthrough();
  }

  return (
    <main className="site-shell">
      <header className="topbar"><div className="brand-lockup"><div className="brand-mark">有</div><div><strong>有界</strong><span>制造计划员工作台</span></div></div><div className="proof-strip" aria-label="验证状态"><Badge variant="outline"><Check /> 67 / 67 tests</Badge><Badge variant="outline"><Check /> 集成对抗 72 / 72</Badge><Badge variant="outline"><Check /> Live 3 × 30</Badge></div></header>
      <div className="page-wrap">
        <LiveAgentWorkbench />
        <div className="walkthrough-divider"><span>运行完上面的真实 Agent，再用下面六步复盘证据链</span></div>
        <section className="intro-row"><div><Badge className="eyebrow">GOAI 2026 · AI + 工业制造</Badge><h1>一次供应延期，从发现影响到执行回流</h1><p>下面所有数字都来自当前可运行案例；工作台展示证据链、恢复方案和人工责任边界，不冒充生产系统。</p></div><div className="legend-card"><span><i className="legend-public" />公开数据派生</span><span><i className="legend-synthetic" />明确模拟</span><span><i className="legend-sandbox" />真实 ERPNext / OpenMES 测试实例 + 合同沙箱</span></div></section>
        <ScenarioHeader />
        <section className="feedback-map" aria-label="核心产品能力">
          <div><span>CAPABILITY 01</span><strong>恢复方案可视化</strong><p>订单影响图、三方案总账、逐单延期与共享时间轴同时呈现。</p><Badge><Check /> 可操作</Badge></div>
          <div><span>CAPABILITY 02</span><strong>ERP / MES 执行闭环</strong><p>命令下发、业务回调、部分失败、旧批准失效与重新求解完整可见。</p><Badge><Check /> 已验证</Badge></div>
        </section>
        <section className="stepper" aria-label="案例步骤">{steps.map((item, index) => {
          const locked = index > 3 && !approved;
          return <button key={item} className={`${index === step ? 'active' : ''} ${index < step ? 'done' : ''}`} onClick={() => setStep(index)} disabled={locked} title={locked ? '完成第 4 步人工批准后解锁' : undefined}><span>{index < step ? <Check /> : index + 1}</span><strong>{item}</strong><small>{locked ? '待审批解锁' : `第 ${index + 1} 步`}</small></button>;
        })}</section>
        <Progress value={progress} className="walk-progress"><ProgressLabel>任务进度 {step + 1} / {steps.length} 步</ProgressLabel><ProgressValue>{(_formattedValue, value) => `${Math.round(value ?? 0)}%`}</ProgressValue></Progress>
        <div className="content-grid">
          <section className="main-stage" aria-live="polite"><div className="stage-heading"><div><span>STEP {String(step + 1).padStart(2, '0')}</span><h2>{steps[step]}</h2></div><Badge variant="secondary">实际案例证据回放</Badge></div>{scene}</section>
          <aside className="evidence-rail"><div className="rail-kicker"><FileCheck2 /> 证据与边界</div><Badge className="feedback-chip">{currentEvidence.capability}</Badge><h3>{currentEvidence.title}</h3><ul>{currentEvidence.items.map((item) => <li key={item}><Check /><span>{item}</span></li>)}</ul><div className="judge-question"><span>为什么可信</span><p>{currentEvidence.explanation}</p></div><div className="agent-boundary"><strong>这一环节谁负责？</strong><div><span>AI / Agent</span><b>{['理解文本','规划查询','编排求解工具','暂停并等待','对账与判断陈旧','触发重新规划'][step]}</b></div><div><span>确定性内核 / 业务系统</span><b>{['实体与字段校验','当前 Demo 自建影响引擎；生产可读取 ERP/MRP/APS 结果','可替换求解器 + verifier','双 hash 门禁','ERP/MES 合同状态机','作废旧批准 + 0 工单'][step]}</b></div><div><span>人</span><b>{step === 3 ? '做最终批准' : step === 5 ? '重新决定' : '保留最终责任'}</b></div></div><div className="rail-boundary"><ShieldCheck /><p>真实 ERPNext / OpenMES 仅本机测试<br />SAP / 金蝶 / 黑湖仍为非认证合同沙箱<br />不控制生产设备</p></div></aside>
        </div>
        <nav className="walk-nav" aria-label="演示导航"><div className="walk-nav-status"><span>六步证据复盘</span><strong>{step + 1} / {steps.length} · {steps[step]}</strong></div><Button variant="outline" size="lg" onClick={goPrevious} disabled={step === 0}><ArrowLeft /> 上一步</Button><Button variant="ghost" size="lg" onClick={reset}><RotateCcw /> 重新演示</Button><div className="next-wrap">{step === 3 && !approved && <span>先由“计划员”批准，才能继续</span>}<Button size="lg" onClick={goNext} disabled={step === steps.length - 1 || (step === 3 && !approved)}>{step === steps.length - 1 ? '演示完成' : '下一步'} <ArrowRight /></Button></div></nav>
        <footer><span>数据口径：Mendeley CC BY 4.0 原始行 + 明确模拟覆盖层</span><span>演示边界：本机测试实例，不替代企业专业决策与生产控制</span></footer>
      </div>
    </main>
  );
}
