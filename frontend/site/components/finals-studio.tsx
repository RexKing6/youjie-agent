'use client';
import {useState,type ReactNode} from 'react';
import {AudioLines,BookOpen,Boxes,ChevronRight,ClipboardCheck,Layers,MessageSquare,Plug,Search,Workflow} from 'lucide-react';
import {Button} from '@/components/ui/button';
import type {HarnessRun} from './harness-workspace';
import {stageForRun,type StudioStage} from '@/lib/finals-stage';

const views:Array<{id:StudioStage;label:string;icon:typeof Search;caption:string}>=[
  {id:'intake',label:'任务输入',icon:MessageSquare,caption:'从一条供应商消息开始'},
  {id:'investigate',label:'Agent 研判',icon:Workflow,caption:'理解目标 · 编排任务 · 调用工具'},
  {id:'evidence',label:'求证与补充',icon:Search,caption:'核对适用范围，让结论有出处'},
  {id:'decision',label:'恢复方案',icon:Layers,caption:'看清成本和交期，再做决定'},
  {id:'execution',label:'执行与反馈',icon:ClipboardCheck,caption:'下达、回读、核对变化、重新规划'},
];
const utilities:Array<{id:StudioStage;label:string;icon:typeof Search}>=[{id:'knowledge',label:'知识库',icon:BookOpen},{id:'skills',label:'技能与连接器',icon:Boxes}];
export function FinalsStudio({stage,onStage,children}:{stage:StudioStage;onStage:(s:StudioStage)=>void;run:HarnessRun|null;busy:string;children:ReactNode}){
 return <div className="studio" data-stage={stage}>
  <aside className="studio-nav"><button type="button" className="studio-brand" onClick={()=>onStage('intake')}><span>界</span><strong>有界<small>制造恢复工作台</small></strong></button>
   <nav aria-label="任务工作区">{views.map((v,i)=><button type="button" key={v.id} aria-current={stage===v.id?'page':undefined} onClick={()=>onStage(v.id)}><v.icon size={18}/><span>{v.label}</span><small>0{i+1}</small></button>)}</nav>
   <nav className="studio-utilities" aria-label="能力与资料">{utilities.map(v=><button type="button" key={v.id} aria-current={stage===v.id?'page':undefined} onClick={()=>onStage(v.id)}><v.icon size={18}/>{v.label}</button>)}</nav>
  </aside>
  <div className="studio-main">
   <div className="studio-content">{children}</div>
  </div>
 </div>;
}

const eventLabels:Record<string,string>={choose_investigation:'选择下一步',execute_tool:'工具返回',understand_reply:'核对补充回答',assess_evidence:'证据完整性核验',targeted_followup:'请人补充',plan_adjustment:'调整计划',invalidate_approval:'旧审批失效',constraint_update:'更新约束',human_approval:'人工批准',execution_feedback:'执行回流',real_execution_feedback:'发现执行变化',execution_reconciled:'人工对账与重算',safe_stop:'安全停止'};
function isHumanGap(e:HarnessRun['trace'][number]){
 const q=e.qualification;
 return e.node==='assess_evidence'&&!!q&&typeof q==='object'&&'gaps' in q&&Array.isArray(q.gaps)&&q.gaps.length>0;
}
function pathLabel(e:HarnessRun['trace'][number]){
 if(isHumanGap(e))return '等待人补充';
 if(e.node!=='execute_tool')return eventLabels[e.node]||e.node;
 return ({query_order:'查询订单',query_quality_stock:'核对库存',retrieve_authorization:'检索经验',query_delivery:'调查供货',solve_recovery:'求解与验证'} as Record<string,string>)[e.tool||'']||e.tool||'工具返回';
}
export function AgentActivity({run,progress=[]}:{run:HarnessRun|null;progress?:Array<{sequence:number;message:string}>}){
 const events=run?.trace.filter(e=>e.node in eventLabels)||[];
 return <section className="studio-activity"><h3><AudioLines size={18}/>实际运行记录</h3>{progress.length>0&&<div className="studio-live-events" aria-live="polite">{progress.map(e=><p key={e.sequence}>{e.message}</p>)}</div>}{!events.length&&!progress.length&&<p className="studio-muted">任务开始后，这里显示真实动作与工具返回。</p>}{[...events].reverse().map(e=><details key={e.sequence}><summary><span className="studio-event-number">{e.sequence}</span><div><small>{eventLabels[e.node]}{e.mcp?' · MCP stdio':''}</small><p>{e.message}</p></div></summary><pre>{JSON.stringify(e,null,2)}</pre></details>)}</section>;
}

export function InvestigationView({run,busy,progress,onStage}:{run:HarnessRun|null;busy:string;progress:HarnessRun['trace'];onStage:(s:StudioStage)=>void}){
 return <InvestigationReasoning run={run} busy={busy} progress={progress} onStage={onStage}/>;
}

function object(value:unknown):Record<string,unknown>{return value&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{};}
export function ModelProgress({events}:{events:HarnessRun['trace']}){
 const turn=Math.max(0,...events.map(e=>e.turn));
 const steps=events.filter(e=>e.node==='model_summary'&&e.turn===turn);
 return <div className="agent-model-progress" aria-live="polite">{steps.length?steps.map(e=><div key={e.sequence}><strong>{typeof e.label==='string'?e.label:'判断摘要'} · {e.progress_status==='complete'?'已完成':e.progress_status==='failed'?'未完成':'处理中'}</strong>{e.message&&<p>{e.message}</p>}</div>):<span>正在接收任务…</span>}</div>;
}
function resultFacts(value:unknown){
 const result=object(value);
 const fields:Record<string,string>={quantity:'订单需求（件）',a1_available:'A1 可用（件）',delay_hours:'延期（小时）',normal_arrival_hour:'常规到货（第几小时）',emergency_arrival_hour:'应急到货（第几小时）',emergency_unit_cost_cny:'应急增量成本（元/件）',approved_limit:'获准替代上限（件）',physical_available:'实物可用（件）',eligible_a2:'本订单可用 A2（件）',verified_material_total:'已核验物料总量（件）',shortfall:'剩余缺口（件）'};
 const facts=Object.entries(fields).filter(([key])=>typeof result[key]==='number');
 return facts.length?<dl className="studio-result-facts">{facts.map(([key,label])=><div key={key}><dt>{label}</dt><dd>{result[key] as number}</dd></div>)}</dl>:null;
}
const gapNames:Record<string,string>={approval_missing:'缺少客户批准',technical_missing:'缺少技术确认',approval_conflict:'批准资料冲突',quality_missing:'缺少质量依据'};
function InvestigationReasoning({run,busy,progress,onStage}:{run:HarnessRun|null;busy:string;progress:HarnessRun['trace'];onStage:(s:StudioStage)=>void}){
 const trace=[...new Map([...(run?.trace||[]),...progress].map(e=>[e.sequence,e])).values()].sort((a,b)=>a.sequence-b.sequence);
 const turn=Math.max(0,...trace.map(e=>e.turn));
 const next=run?stageForRun(run):'intake';
 const qualification=object([...trace].reverse().find(e=>e.qualification)?.qualification);
 const gaps=Array.isArray(qualification.gaps)?qualification.gaps.map(String):[];
 const clean=(text:string)=>text.replaceAll('O-208','X').replaceAll('approval_missing','缺少客户批准').replaceAll('technical_missing','缺少技术确认');
 function timeline(round:number){
  const events=trace.filter(e=>e.turn===round);
  const actions=events.filter(e=>['choose_investigation','targeted_followup','assess_evidence','understand_reply','plan_adjustment','safe_stop','understand_incident'].includes(e.node)||e.node==='execute_tool'&&!events.some(c=>c.node==='choose_investigation'&&c.selected_tool===e.tool&&c.sequence<e.sequence));
  return <ol className="agent-action-list">{actions.map(e=>{
   const followingChoice=events.find(c=>c.node==='choose_investigation'&&c.sequence>e.sequence);
   const result=e.node==='choose_investigation'?events.find(c=>c.node==='execute_tool'&&c.tool===e.selected_tool&&c.sequence>e.sequence&&(!followingChoice||c.sequence<followingChoice.sequence)):e.node==='execute_tool'?e:undefined;
   const skill=object(result?.skill||e.skill);
   const output=object(result?.result);
   const citation=object(e.citation);
   const sources=Array.isArray(output.sources)?output.sources.filter((s):s is string=>typeof s==='string'):[];
   return <li key={e.sequence}><article>
    <header><strong>{e.node==='choose_investigation'?`Agent 选择：${pathLabel({...e,node:'execute_tool',tool:e.selected_tool})}`:e.node==='targeted_followup'?'Agent 向你求证':pathLabel(e)}</strong></header>
    <p>{clean(e.message)}</p>
    {isHumanGap(e)&&<p className="agent-action-evidence">现有材料不足以确认本订单可以使用替代件，需要补齐对应证据后再决定。</p>}
    {typeof e.context==='string'&&<p className="agent-action-evidence">{clean(e.context)}</p>}
    {typeof citation.quote==='string'&&<blockquote>{citation.quote}</blockquote>}
    {result&&<div className="agent-action-result"><div><code>{result.mcp?'MCP Tool · ':'Tool · '}{result.tool}</code>{typeof skill.name==='string'&&<small>Skill · {skill.name}</small>}</div>{resultFacts(result.result)}{sources.length>0&&<p>查到资料：{sources.join('、')}</p>}{!sources.length&&!resultFacts(result.result)&&<p>{clean(result.message)}</p>}</div>}
    {e.node==='choose_investigation'&&!result&&<div className="agent-action-result"><code>{e.selected_tool}</code>{typeof skill.name==='string'&&<small> · Skill · {skill.name}</small>}<p>{busy?'调用中…':'未取得返回'}</p></div>}
    <details><summary>查看调用与证据详情</summary><pre>{JSON.stringify({action:e,...(result?{result}:{})},null,2)}</pre></details>
   </article></li>;
  })}</ol>;
 }
 return <section id="investigation-result" tabIndex={-1} className="agent-journal" aria-label="Agent行动时间线">
  {Array.from({length:turn+1},(_,i)=><section key={i}>{timeline(i)}</section>)}
  {busy&&<output className="agent-journal-progress" aria-live="polite">正在处理…</output>}
  {run&&!busy&&<section className="agent-journal-next"><strong>{next==='decision'?'恢复方案已生成':next==='execution'?'进入执行核对':next==='investigate'?'本次分析未完成':'需要你补充信息'}</strong>
   {next==='evidence'&&gaps.length>0&&<p>{gaps.map(g=>gapNames[g]||g).join('；')}。</p>}
   <Button onClick={()=>onStage(next==='investigate'?'evidence':next)}>{next==='decision'?'查看恢复方案':next==='execution'?'查看执行反馈':next==='investigate'?'查看问题详情':'去补充信息'}</Button>
  </section>}
  {!run&&!busy&&<Button onClick={()=>onStage('intake')}>输入供应商消息</Button>}
 </section>;
}


export function SessionCapabilities({catalog,sources,onStage}:{catalog?:NonNullable<HarnessRun['harness']>['skills'];sources?:Array<{id:string;title:string}>;externalEnabled:boolean;onStage:(s:StudioStage)=>void}){
 const [open,setOpen]=useState<string|null>(null);
 return <div className="session-tags" aria-label="本次会话能力">
  <button type="button" className="session-tag" data-kind="mcp" aria-expanded={open==='mcp'} aria-controls="session-tag-panel" onClick={()=>setOpen(open==='mcp'?null:'mcp')}><Plug size={13}/>MCP Server<ChevronRight size={12}/></button>
  <button type="button" className="session-tag" data-kind="skills" aria-expanded={open==='skills'} aria-controls="session-tag-panel" onClick={()=>setOpen(open==='skills'?null:'skills')}><Boxes size={13}/>Skills<ChevronRight size={12}/></button>
  <button type="button" className="session-tag" data-kind="knowledge" aria-expanded={open==='knowledge'} aria-controls="session-tag-panel" onClick={()=>setOpen(open==='knowledge'?null:'knowledge')}><BookOpen size={13}/>知识库<ChevronRight size={12}/></button>
  {open&&<section id="session-tag-panel" className="session-tag-panel"><header><strong>{open==='mcp'?'MCP Server':open==='skills'?'已配置 Skills':'订单替代料知识库'}</strong><button type="button" onClick={()=>setOpen(null)} aria-label="关闭能力详情">×</button></header>
   {open==='mcp'&&<ul><li><strong>ERPNext</strong><p>查询业务单据、创建草稿与回读</p></li><li><strong>OpenMES</strong><p>下达生产任务、读取执行进度</p></li><li><strong>业务查询与规划求解器</strong><p>查询库存与供货、计算恢复方案</p></li></ul>}
   {open==='skills'&&<ul>{catalog?.map(s=><li key={s.id}><strong>{s.name}</strong><p>{s.output}</p></li>)}</ul>}
   {open==='knowledge'&&<><ul>{sources?.filter(s=>s.id!=='MAIL-DELAY').map(s=><li key={s.id}>{s.title.replace(/（模拟[^）]*）/g,'').replaceAll('O-208','X')}</li>)}</ul><Button variant="outline" onClick={()=>onStage('knowledge')}>阅读资料原文</Button></>}
  </section>}
 </div>;
}

export function CapabilityView({run,catalog,externalEnabled}:{run:HarnessRun|null;catalog?:NonNullable<HarnessRun['harness']>['skills'];externalEnabled:boolean}){
 const toolDescriptions:Record<string,{title:string;description:string}>={
  erp_health:{title:'检查 ERP 连接',description:'检查 ERPNext 接口是否可访问、当前凭据能否正常认证。'},
  erp_list:{title:'查找业务单据',description:'按单据类型和筛选条件查询 ERPNext，找到需要核对的物料、BOM 或工单记录。'},
  erp_read:{title:'读取单据详情',description:'根据单据类型和编号读取完整记录，用于核对字段及写入后的结果。'},
  erp_create_draft:{title:'创建业务草稿',description:'将人工批准的交付内容写成 ERPNext 草稿单据，保留后续业务审核环节。'},
  mes_health:{title:'检查 MES 连接',description:'检查 OpenMES 接口是否可访问、认证是否正常。'},
  mes_read:{title:'查看生产执行状态',description:'按工单编号读取 OpenMES 中的执行快照，供系统核对进度及状态变化。'},
  mes_import:{title:'导入生产工单',description:'将获准下达的任务导入 OpenMES，并取得导入结果，供后续跟踪执行。'},
  retrieve_authorization:{title:'查找替代依据',description:'从本任务可访问的历史记录和证明材料中检索相关资料，返回原文，供核对批准范围及技术条件。'},
  query_order:{title:'核对订单需求',description:'读取本任务订单快照中的需求数量、A1 可用量及延期信息，明确受影响的物料缺口。'},
  query_quality_stock:{title:'核对质量与库存',description:'查询本任务的库存快照和质量证明来源，供核对替代件的可用数量与批次条件。'},
  query_delivery:{title:'比较补货来源',description:'查询案例中各供货来源的到货时间和增量单价，为应急补货方案提供数据。'},
  solve_recovery:{title:'生成恢复方案',description:'使用 CP-SAT 在物料、产能和交期约束内求解排程，并校验方案，输出成本和交付结果。'},
 };
 const [tab,setTab]=useState<'connectors'|'skills'>('connectors');
 const [connector,setConnector]=useState('ERPNext');
 const [selected,setSelected]=useState('');
 const skills=run?.harness?.skills||catalog||[];
 const skill=skills.find(s=>s.id===selected)||skills[0];
 const groups=[{name:'ERPNext',description:'业务单据：读取订单相关单据、创建生产草稿并回读',tools:['erp_health','erp_list','erp_read','erp_create_draft'],boundary:'创建草稿需经过人工批准与服务端校验。'}, {name:'OpenMES',description:'生产执行：导入任务、读取工单执行状态',tools:['mes_health','mes_read','mes_import'],boundary:'只连接测试业务系统，不控制设备。'}, {name:'知识库',description:'检索历史记录、批准资料及其适用范围',tools:['retrieve_authorization'],boundary:'检索结果不等于批准，需核对来源、订单、物料和批次。'}, {name:'业务查询与规划求解器',description:'查询案例订单、质量库存、供货信息，计算恢复方案',tools:['query_order','query_quality_stock','query_delivery','solve_recovery'],boundary:'查询与求解本案例数据，不代表直接读取真实工厂现场。'}];
 const group=groups.find(g=>g.name===connector)||groups[0];
 return <><div className="studio-capability-tabs"><Button variant={tab==='connectors'?'default':'outline'} onClick={()=>setTab('connectors')}><Plug size={16}/>连接器与工具</Button><Button variant={tab==='skills'?'default':'outline'} onClick={()=>setTab('skills')}>技能</Button></div>
 {tab==='connectors'?<div className="studio-skill-browser"><section><h2>连接器</h2><p>同一个 MCP 服务内的不同能力组。</p>{groups.map(g=><button key={g.name} aria-pressed={g.name===group.name} onClick={()=>setConnector(g.name)}><strong>{g.name}</strong><small>{g.tools.length} 项工具</small></button>)}</section><article><h2>{group.name}</h2><p>{group.description}</p><p>{group.boundary}</p>{['ERPNext','OpenMES'].includes(group.name)&&<small>{externalEnabled?'后端已配置接入':'尚未确认接入配置'}；配置状态不等于健康检查通过。</small>}<h3>MCP tools</h3>{group.tools.map(tool=>{const calls=run?.trace.filter(e=>e.tool===tool||object(e.mcp).tool===tool)||[];return <section className="studio-tool-detail" key={tool}><h4>{toolDescriptions[tool].title}</h4><code>{tool}</code><p>{toolDescriptions[tool].description}</p>{calls.length>0&&<details><summary>查看本任务调用记录（{calls.length}）</summary>{calls.map(e=><pre key={e.sequence}>{JSON.stringify(e,null,2)}</pre>)}</details>}</section>;})}</article></div>:
 <div className="studio-skill-browser"><section><h2>可复用技能</h2><p>任务步骤、输入输出和工具权限；不是多个独立 Agent。</p>{skills.length?skills.map(s=><button type="button" aria-pressed={s.id===skill?.id} key={s.id} onClick={()=>setSelected(s.id)}><strong>{s.name}</strong><small>v{s.version} · {s.tools.length}项工具</small></button>):<p>任务建立后，从服务端加载本次使用的技能契约。</p>}</section>{skill&&<article><span className="studio-kicker">SKILL CONTRACT / v{skill.version}</span><h2>{skill.name}</h2><h3>输入</h3><p>{skill.inputs.join('、')}</p><h3>执行步骤</h3><ol>{skill.steps.map(s=><li key={s}>{s}</li>)}</ol><h3>工具</h3><div className="studio-tool-tags">{skill.tools.map(t=><code key={t}>{t}</code>)}</div><h3>交付</h3><p>{skill.output}</p><h3>权限边界</h3><p>{skill.boundary}</p></article>}</div>}</>;
}
