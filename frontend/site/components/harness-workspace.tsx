'use client';
import {useState, type ReactNode} from 'react';

type Skill = {id:string;name:string;version:string;status:string;inputs:string[];steps:string[];tools:string[];output:string;boundary:string};
type Event = {sequence:number;turn:number;node:string;message:string;tool?:string;selected_tool?:string;[key:string]:unknown};
export type HarnessRun = {
  run_id:string;revision:number;status:string;mode:string;trace:Event[];
  harness?:{orchestrator:string;skills:Skill[];human_mode:string;shortfall?:number};
  supply_offers?:{offers:Array<{source:string;arrival_hour:number;incremental_unit_cost:number}>};
};
const labels:Record<string,string>={pending:'待执行',done:'已取得结果',waiting_human:'等你确认',monitoring:'可查看执行',skipped:'物料够用，无需补货'};
const anchors:Record<string,string>={impact:'evidence-step',knowledge:'evidence-step',supply:'supply-investigation',decision:'plan-comparison',execution:'execution-delivery'};

export function HarnessWorkspace({run,children}:{run:HarnessRun;children:ReactNode}) {
  const [all,setAll]=useState(false);
  const events=run.trace.filter(t=>['choose_investigation','execute_tool','targeted_followup','plan_adjustment','invalidate_approval','constraint_update','human_approval','execution_feedback','erp_execute','mes_execute','execution_poll','safe_stop'].includes(t.node));
  return <section className="harness" aria-label="Agent任务工作台">
    <header className="harness-title"><div><small>有界 Agent Harness</small><h2>订单X · 从异常到恢复执行</h2></div><span>{run.mode==='live'?'在线模型':'离线测试'} · 同一任务第{run.revision}版</span></header>
    <div className="harness-layout">
      <aside className="harness-plan" aria-label="当前任务计划"><h3>任务计划</h3><p>根据证据选择下一步，不要求按卡片顺序执行。</p>
        {run.harness?.skills.map((s,i)=><article key={s.id} data-status={s.status}><a href={`#${anchors[s.id]}`}><small>{String(i+1).padStart(2,'0')} · {labels[s.status]||s.status}</small><strong>{s.name}</strong></a>
          <details><summary>查看 Skill</summary><small>v{s.version}</small><p>输入：{s.inputs.join('、')}</p><ol>{s.steps.map(step=><li key={step}>{step}</li>)}</ol><p>交付：{s.output}</p><p>{s.boundary}</p><code>{s.tools.join(' / ')}</code></details>
        </article>)}
        <div className="harness-human"><strong>{run.harness?.human_mode==='on_the_loop'?'Human-on-the-loop':'Human-in-the-loop'}</strong><p>{run.harness?.human_mode==='on_the_loop'?'人监督执行，点击刷新核对变化；变化后重新确认。':'需要证据或批准时由人介入；补充后继续核验，不把回答当授权。'}</p></div>
      </aside>
      <div className="harness-business">{run.supply_offers && <section id="supply-investigation" className="wiki-section"><h2>应急供货调查</h2><p>当前已核验缺口：{run.harness?.shortfall??'待核对'}件。以下为模拟合格来源，未联系真实供应商。</p><div className="harness-offers">{run.supply_offers.offers.map(o=><article key={o.source}><strong>{o.source}</strong><p>第{o.arrival_hour}小时到货</p><span>追加 ¥{o.incremental_unit_cost}/件</span></article>)}</div></section>}{children}</div>
      <aside className="harness-trace" aria-label="Agent实际执行轨迹"><h3>Agent 做了什么</h3><p>行动摘要与真实返回；不是模型内部思维链。每轮完成后更新。</p><small>一个编排Agent · LangGraph</small>
        {(all?events:events.slice(-8)).map(e=><details key={e.sequence} className="harness-event"><summary><small>#{e.sequence} · 补证轮次{e.turn}</small><strong>{e.message}</strong><span>{e.mcp?'MCP · stdio':e.tool||e.selected_tool||'状态与人类介入'}</span></summary><pre>{JSON.stringify(e,null,2)}</pre></details>)}
        {!events.length&&<p>还没有执行记录。</p>}
        {events.length>8&&<button type="button" onClick={()=>setAll(!all)}>{all?'只看最近8条':`查看全部${events.length}条`}</button>}
      </aside>
    </div>
  </section>;
}
