'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { KnowledgeOverview } from '@/components/knowledge-overview';
import type { HarnessRun } from '@/components/harness-workspace';
import {FinalsStudio,InvestigationView,CapabilityView,SessionCapabilities} from './finals-studio';
import {stageForRun,stageAfterAnalysis,type StudioStage} from '@/lib/finals-stage';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import {
  BookOpen,
  ChevronRight,
  GitBranch,
  LoaderCircle,
} from 'lucide-react';
import {
  FinalsExecutionPanel,
  type ExecutionDetails,
} from './finals-execution-panel';

const API = 'http://127.0.0.1:8766';
let sessionCapability = '';
type Doc = { id: string; title: string; role: string; body: string };
export type Run = HarnessRun & {
  capacity_event?: {status:string;start_hour?:number;end_hour?:number};
  decision_budget?: number;
  failure?: unknown;
  runtime_compatible?: boolean;
  resume_warning?: string;
  run_id: string;
  revision: number;
  current_hour?: number;
  status: string;
  mode: string;
  policy: string;
  model_name: string;
  reply_count: number;
  question: string;
  active_documents: string[];
  known_sources?: string[];
  knowledge_updates?: Array<{revision: number; document_ids: string[]; version: string; scope: string; mode: string}>;
  a1_quarantine_event?: {quantity: number; previous_a1: number; remaining_a1: number; synthetic: boolean};
  tool_calls: number;
  model_calls: number;
  duration_ms: number;
  messages: Array<{ role: string; text: string; documents?: string[] }>;
  wiki: {
    version: string;
    mode: string;
    claims: Array<{
      summary: string;
      untrusted_model_summary: boolean;
      citation: {
        document_id: string;
        source_hash: string;
        start: number;
        end: number;
        quote: string;
      };
    }>;
    conflicts: Array<{ kind: string; sources: string[]; message: string }>;
  };
  qualification?: {
    status: string;
    gaps: string[];
    approved_limit: number;
    physical_available: number;
    eligible_a2: number;
    verified_material_total: number;
    shortfall: number;
    sources: string[];
  };
  order: { quantity: number; a1_available: number; delay_hours: number };
  case_id: string;
  stock: { on_hand: number; hold: number; revision: number };
  trace: Array<{
    sequence: number;
    turn: number;
    node: string;
    message: string;
    tool?: string;
    selected_tool?: string;
    [key: string]: unknown;
  }>;
  plans: Array<{
    plan: {
      plan_id: string;
      profile: string;
      order_outcomes: Array<{
        completion_hour: number | null;
        late_hours: number;
        scheduled: boolean;
      }>;
      scheduled_operations: Array<{ start_hour: number; end_hour: number }>;
      evidence: { verified: boolean };
      purchases: Array<{ source_id: string; quantity: number }>;
    };
    summary: {
      recovery_cost: number;
      first_due_on_time_units: number;
      first_due_late_units: number;
    };
  }>;
  approval: { valid: boolean; approval_id: string } | null;
  drafts: unknown[];
  history?: unknown[];
  execution?: ExecutionDetails;
  pending_execution_event?: {
    event_id: string;
    produced_qty: number;
    order_no: string;
  };
  completed_good?: number;
  original_order_quantity?: number;
  external_followup?: string;
  wiki_refresh_error?: { error_code: string };
};
const STATES: Record<string, string> = {
  no_disruption: '没有供应延期，不生成恢复工单',
  awaiting_evidence: '等待补充证据',
  needs_input: '需要明确输入',
  paused: '安全暂停',
  awaiting_approval: '方案已核验，等待审批',
  approved_local_drafts: '已批准本地草稿',
  needs_reconciliation: '执行已变化，等待对账',
  completed: '对账确认已完成',
  model_or_validation_error: '运行未完成，已安全停止',
};
const TOOLS: Record<string, string> = {
  query_order: '订单与客户要求',
  retrieve_authorization: '知识库与批准依据',
  query_quality_stock: '批次质量与库存',
  query_delivery: '供应交期',
};
const PROFILES: Record<string, string> = {
  service_first: '保交期',
  balanced: '预算内折中',
  stability_first: '不追加成本',
};
export type Bootstrap = {
  skills?: NonNullable<HarnessRun['harness']>['skills'];
  cases: Array<{ id: string; label: string }>;
  sources: Doc[];
  evidence_bundles?: Record<string,string[]>;
  live_enabled: boolean;
  external_enabled: boolean;
  session_capability: string;
  max_replies?: number | null;
};
type Comparison = { runs: Run[]; disclosure: string };
type Budget = {
  enabled: boolean;
  available: boolean;
  message?: string;
  requests?: number;
  limit_requests?: number | null;
  limit_cny?: number | null;
  accounted_cny?: number;
  uncertain_requests?: number;
  can_dispatch?: boolean;
};
type Responses = {
  '/bootstrap': Bootstrap;
  '/budget': Budget;
  '/compare': Comparison;
  '/wiki': Run;
  '/start': Run;
  '/reply': Run;
  '/constraints/budget': Run;
  '/approve': Run;
  '/feedback': Run;
  '/feedback/a1-quarantine': Run;
  '/resume': Run;
  '/integrations/execute': Run;
  '/integrations/reconcile': Run;
  '/feedback/poll': Run;
  '/feedback/demo-progress': Run;
  '/feedback/capacity': Run;
  '/feedback/capacity-replan': Run;
  '/feedback/confirm': Run;
};

function describeFailure(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '';
  const parts: string[] = [];
  if ('error_code' in value && typeof value.error_code === 'string') parts.push(value.error_code);
  if ('recovery_action' in value && typeof value.recovery_action === 'string') parts.push(value.recovery_action);
  if ('external_records' in value && value.external_records && typeof value.external_records === 'object') {
    const labels: Record<string, string> = {none: '未记录写入', known: '已有记录', unknown: '结果未知，先查回'};
    for (const [system, status] of Object.entries(value.external_records)) {
      if ((system === 'erp' || system === 'mes') && typeof status === 'string' && status in labels)
        parts.push(`${system.toUpperCase()}：${labels[status]}`);
    }
  }
  return parts.join('；');
}

async function request<P extends keyof Responses>(
  path: P,
  payload?: unknown,
): Promise<Responses[P]> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 120000);
  try {
    const r = await fetch(API + path, {
      method: payload ? 'POST' : 'GET',
      signal: controller.signal,
      headers: payload
        ? {
            'Content-Type': 'application/json',
            'X-Youjie-Session': sessionCapability,
          }
        : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const data: unknown = await r.json();
    if (!data || typeof data !== 'object' || Array.isArray(data))
      throw new Error('服务返回无效对象');
    if (!r.ok) {
      const diagnostic = 'failure' in data ? describeFailure(data.failure) : '';
      throw new Error(diagnostic || ('message' in data && typeof data.message === 'string' ? data.message : '请求未完成'));
    }
    return data as Responses[P];
  } finally {
    window.clearTimeout(timer);
  }
}

const MESSAGE_PRESETS = [
  {id: 'delay', label: '原料延期两天', text: '连接件A1预计比原定到货时间晚48小时。'},
  {id: 'short_delay', label: '原料延期一天', text: '连接件A1预计比原定到货时间晚24小时。'},
  {id: 'long_delay', label: '原料延期三天', text: '连接件A1预计比原定到货时间晚72小时。'},
  {id: 'missing', label: '通知没说清是哪种物料、晚多久', text: '那批连接件今天发不了了。'},
  {id: 'uncertain', label: '到货时间还不确定', text: '连接件A1到货可能延期24小时，也可能延期48小时，尚未确认。'},
  {id: 'invalid', label: '测试无关消息', text: '你好，今天吃什么？'},
];

const REPLY_PRESETS = [
  {id: 'oral', label: '只听同事说可以用，还没有材料', text: '王工说A2可以用，但我还没有找到他针对本订单的确认记录。', document: ''},
  {id: 'partial', label: '找到本订单批准：允许使用300个A2', text: '找到本订单的技术确认和客户批准，允许使用300个A2，请核对附件。', document: 'AP-PARTIAL'},
  {id: 'full', label: '找到本订单批准：允许使用400个A2', text: '找到本订单的技术确认和客户批准，允许使用400个A2，请核对附件。', document: 'AP-CURRENT'},
  {id: 'unknown', label: '暂时找不到确认材料', text: '目前找不到本订单的确认材料，请不要把A2算作已获准使用。', document: ''},
];

function readableMessage(text: string) {
  return text
    .replace(/（模拟[^）]*）/g, '')
    .replaceAll('缺少客户乙、订单O-208、B版、A2/B17替代A1的有效批准。', '还没找到本订单客户同意使用A2的批准记录。')
    .replaceAll('缺少客户乙O-208/B版/B17的技术适用确认，历史客户甲技术意见不能代替。', '还没找到技术人员确认这批A2符合本订单要求的记录。已有的技术意见只针对另一位客户的旧订单，不能直接用于这次。')
    .replaceAll('O-208', 'X');
}

function dialogueMessage(text:string){
  const followup=text.match(/模型追问（不构成批准）：([\s\S]*?)(?:必须补齐：|$)/);
  const context=text.match(/模型依据解释（待核实）：([\s\S]*?)\n模型追问/);
  if(followup)return readableMessage([context?.[1].trim(),followup[1].trim()].filter(Boolean).join('\n\n'));
  if(text.startsWith('缺少客户乙、订单O-208')&&text.includes('技术适用确认'))return '这笔订单能否使用 A2，还缺客户批准和技术确认。你有这两份材料吗？如果目前只听同事说过，也可以先告诉我。';
  return readableMessage(text);
}

const SOURCE_NAMES: Record<string, string> = {src_emergency: '应急配送', src_regional: '区域调拨', src_normal: '等原供应商'};
function purchaseDescription(purchases: Run['plans'][number]['plan']['purchases']) {
  return purchases.filter(p => p.quantity > 0).map(p => `${SOURCE_NAMES[p.source_id] || p.source_id} ${p.quantity}个A1`).join(' + ') || '现有合格物料已够用';
}

function AnalysisMessage({text}: {text: string}) {
  const plain = readableMessage(text);
  const initialGap = '还没找到本订单客户同意使用A2的批准记录。还没找到技术人员确认这批A2符合本订单要求的记录。已有的技术意见只针对另一位客户的旧订单，不能直接用于这次。';
  if (plain.replace(/\s/g, '') !== initialGap) return <p>{plain}</p>;
  return <div className="wiki-gap-summary">
    <p><strong>还缺两项确认：</strong></p>
    <ul style={{listStyleType: 'disc', paddingLeft: 22, margin: '8px 0 16px', display: 'grid', gap: 8}}>
      <li><strong>客户批准：</strong>还没找到本订单客户同意使用A2的记录。</li>
      <li><strong>技术确认：</strong>还没找到技术人员确认这批A2符合本订单要求的记录。</li>
    </ul>
    <p><strong>为什么旧记录不够？</strong><br />已有的技术意见只针对另一位客户的旧订单，不能直接用于这次。</p>
  </div>;
}

export function WikiWorkbench({preview}:{preview?:{boot:Bootstrap;run:Run|null;stage:StudioStage}}={}) {
  const [stage,setStage]=useState<StudioStage>(preview?.stage ?? 'intake');
  function navigate(next:StudioStage){setStage(next);window.scrollTo({top:0,behavior:'instant'});}
  const [boot, setBoot] = useState<Bootstrap | null>(preview?.boot ?? null);
  const [error, setError] = useState('');
  const [previewNotice,setPreviewNotice]=useState('');
  const [busy, setBusy] = useState('');
  const [progress,setProgress]=useState<HarnessRun['trace']>([]);
  useEffect(()=>{
    if(preview||!busy)return;
    const since=Date.now()/1000;
    let active=true;
    const timer=window.setInterval(async()=>{
      try{
        const response=await fetch(API+'/progress',{headers:{'X-Youjie-Session':sessionCapability}});
        if(!response.ok)return;
        const data=await response.json();
        if(active&&data&&typeof data==='object'&&'updated_at' in data&&typeof data.updated_at==='number'&&data.updated_at>=since&&'events' in data&&Array.isArray(data.events)) {
          setProgress(data.events.filter((e:unknown):e is HarnessRun['trace'][number]=>!!e&&typeof e==='object'&&'sequence' in e&&typeof e.sequence==='number'&&'message' in e&&typeof e.message==='string'&&'node' in e&&typeof e.node==='string'&&'turn' in e&&typeof e.turn==='number'));
        }
      }catch{/* Main request owns error recovery; polling cannot change run state. */}
    },250);
    return()=>{active=false;window.clearInterval(timer);};
  },[busy]);
  const [text, setText] = useState(MESSAGE_PRESETS[0].text);
  const [messagePreset, setMessagePreset] = useState('delay');
  const [reply, setReply] = useState('');
  const [replyPreset, setReplyPreset] = useState('custom');
  const [replyError, setReplyError] = useState('');
  const [, setReplyNotice] = useState('');
  const replyResultPending = useRef(false);
  const latestAnswer = useRef<HTMLElement | null>(null);
  const pendingAnswer = useRef<HTMLElement | null>(null);
  useEffect(()=>{
    if(busy==='核对补充信息')pendingAnswer.current?.scrollIntoView({behavior:'smooth',block:'nearest'});
  },[busy]);
  const caseId = 'guided';
  const policy = 'adaptive';
  const mode = 'live';
  const [attachment, setAttachment] = useState('');
  const [actor, setActor] = useState('演练计划员');
  const [run, setRun] = useState<Run | null>(preview?.run ?? null);
  const [comparison, setComparison] = useState<{
    runs: Run[];
    disclosure: string;
  } | null>(null);
  const [wiki, setWiki] = useState<Run['wiki'] | null>(null);

  useEffect(() => {
    if(preview)return;
    request('/bootstrap')
      .then((value) => {
        setBoot(value);
        sessionCapability = value.session_capability;
      })
      .catch(() => setError('本机调查服务未连接（8766）。原有演示不受影响。'));
  }, []);
  useEffect(() => {
    if (!replyResultPending.current || !run) return;
    replyResultPending.current = false;
    const target = stage==='evidence' ? latestAnswer.current : stageForRun(run)==='execution' ? document.getElementById('execution-delivery') : document.getElementById('investigation-result');
    target?.scrollIntoView({behavior: 'smooth', block: 'start'});
    target?.focus({preventScroll: true});
  }, [run,stage]);
  async function act(label: string, work: () => Promise<void>) {
    if(preview){setPreviewNotice('请用顶部情节按钮查看已记录的结果。');return;}
    setProgress([]);
    setBusy(label);
    setError('');
    try {
      await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作未完成');
    } finally {
      setBusy('');
    }
  }
  function showRun(value: Run, destination?: StudioStage) {
    navigate(destination ?? stageAfterAnalysis(value));
    setRun(value);
    setWiki(value.wiki);
    setReply('');
    setReplyPreset('custom');
    setAttachment('');
    localStorage.setItem(
      'youjie-finals-last-run',
      JSON.stringify({ run_id: value.run_id, revision: value.revision }),
    );
  }
  function showRunWithNavigation(value: Run) {
    replyResultPending.current = true;
    showRun(value);
  }
  const canReply =
    run &&
    run.runtime_compatible !== false &&
    ['awaiting_evidence', 'needs_input'].includes(run.status);
  const activeWiki = wiki || run?.wiki;
  const q = run?.qualification;

  return (
    <FinalsStudio stage={stage} onStage={navigate} run={run} busy={busy}>
    <main className="wiki-shell studio-body">
      {previewNotice&&<p role="status">{previewNotice}</p>}
      <div hidden={stage!=='intake'} className="studio-intake">
      <section className="wiki-story" aria-label="案例背景">
        <span className="studio-kicker">工厂内部订单 / X</span><h2>600件成品，原计划12小时交货</h2>
        <p>需要600个A1连接件。你是生产计划员，刚收到供应商的延期消息。</p>
        <details><summary>案例说明</summary><p>这是模拟订单X；A1是原定连接件。库存、替代料和历史记录会在分析后展示。当前支持本订单的延期0–72小时和需求1–1200件；不明确或超出范围时会要求说明，不代表支持任意工厂任务。</p></details>
      </section>
      <section id="incident-input" className="wiki-input" aria-label="任务输入">
        <h2>供应商发来了什么？</h2>
        <label htmlFor="message-preset">消息类型：</label>
        <NativeSelect id="message-preset" aria-label="选择供应商消息" value={messagePreset} disabled={!!busy}
          onChange={(e) => {setMessagePreset(e.target.value); const preset = MESSAGE_PRESETS.find(p => p.id === e.target.value); setText(preset?.text ?? '');}}>
          {MESSAGE_PRESETS.map(p => <NativeSelectOption key={p.id} value={p.id}>{p.label}</NativeSelectOption>)}
          <NativeSelectOption value="custom">自定义消息</NativeSelectOption>
        </NativeSelect>
        <label htmlFor="task-text">发送给有界的消息内容（可编辑）：</label>
        <Textarea
          id="task-text"
          value={text}
          onChange={(e) => {setText(e.target.value); setMessagePreset('custom');}}
          maxLength={6000}
          disabled={!!busy}
        />
        <div className="wiki-actions session-submit-row">
          <SessionCapabilities catalog={boot?.skills} sources={boot?.sources} externalEnabled={!!boot?.external_enabled} onStage={navigate}/>
          <Button
            disabled={!!busy || !boot || !text.trim()}
            onClick={() =>
              act('分析订单与可用物料', async () => {
                navigate('investigate');
                setRun(null);
                setWiki(null);
                setReplyError('');
                setReplyNotice('');
                setComparison(null);
                showRun(
                  await request('/start', {
                    text,
                    case_id: caseId,
                    policy,
                    mode,
                  }),
                );
              })
            }
          >
            {run ? '按新消息重新分析' : '分析这次延期'} <ChevronRight size={16} />
          </Button>
        </div>
      </section>
      </div>
      <div hidden={stage!=='investigate'}><InvestigationView run={run} busy={busy} progress={progress} onStage={navigate}/></div>
      <div hidden={stage!=='skills'}><CapabilityView run={run} catalog={boot?.skills} externalEnabled={!!boot?.external_enabled}/></div>
      <div hidden={stage!=='knowledge'}><KnowledgeOverview sources={boot?.sources} checkedIds={run ? run.known_sources || [] : undefined} claims={activeWiki?.claims}/></div>
      {busy && stage !== 'investigate' && busy !== '核对补充信息' && (
        <div className="wiki-busy" aria-live="polite">
          <LoaderCircle className="animate-spin" size={20} aria-hidden="true" />
          <div className="wiki-busy-copy">
            <strong>{busy}</strong>
            <span>正在处理，请稍候。不会自动批准。</span>
          </div>
        </div>
      )}
      {error && (
        <div className="wiki-error" role="alert">
          <p>{error}</p>
          <p>请求未确认完成，请勿连续点击。{run?.execution ? '已有业务交付记录，先检查原任务，不重新下单。' : '通信中断不等于处理失败，请先检查服务和任务状态。'}</p>
          <Button disabled={!!busy} onClick={() => act('检查服务与当前任务', async () => {
            const value = await request('/bootstrap');
            setBoot(value); sessionCapability = value.session_capability;
            if (run) showRun(await request('/resume', {run_id: run.run_id, revision: run.revision}));
          })}>检查服务与当前任务</Button>
          <Button variant="outline" onClick={()=>navigate(run?.execution?'execution':'intake')}>{run?.execution ? '查看交付记录' : '回到输入区'}</Button>
        </div>
      )}
      {run?.runtime_compatible === false && (
        <p className="wiki-error" role="alert">
          此任务仅可查看或导出：运行版本已变化或缺少历史版本记录。请在上方点击“按新消息重新分析”，旧的确认结果不能继续使用。
        </p>
      )}
      {run ? (
        <>
          {run.status === 'model_or_validation_error' && <div className="wiki-error" role="alert">
            <strong>分析未完成</strong><p>{run.question}</p>
            <p>{run.execution ? '已有业务系统记录。先查看交付状态，不重复下达。' : '尚未进入业务系统交付。本次没有生成可供审批的新方案。'}</p>
            <Button variant="outline" onClick={()=>navigate(run.execution?'execution':'intake')}>{run.execution ? '查看原任务交付记录' : '回到输入区，重新发起分析'}</Button>
            <details><summary>查看错误类别</summary>{describeFailure(run.failure)}</details>
          </div>}
          {run.status !== 'awaiting_evidence' && run.status !== 'model_or_validation_error' && describeFailure(run.failure) && (
            <p className="wiki-note" aria-live="polite">下一步：{describeFailure(run.failure)}</p>
          )}
          {run.wiki_refresh_error && (
            <p className="wiki-error">
              本次知识库 刷新失败：{run.wiki_refresh_error.error_code}
              。下方保留的是上一有效版本。
            </p>
          )}
          {run.completed_good !== undefined && (
            <p className="wiki-note">
              原订单 {run.original_order_quantity} 件；对账确认已完成{' '}
              {run.completed_good} 件；剩余计划 {run.order.quantity}{' '}
              件。不是新增一张完整订单。
            </p>
          )}
          <div hidden={stage!=='evidence'} className="studio-evidence-layout">
            <section id="evidence-step" className="wiki-section wiki-conversation">
              {!!run.knowledge_updates?.length && <aside className="wiki-knowledge-update" aria-label="本次知识更新">
                <strong>新证明已纳入本次知识库</strong>
                <p>{run.knowledge_updates.flatMap(u => u.document_ids).map(id => boot?.sources.find(d => d.id === id)?.title || id).join('、')}。接下来的判断引用这些资料及其适用范围，不把口头答复当成批准。</p>
                <Button variant="outline" onClick={()=>navigate('knowledge')}>查看来源与当前知识版本</Button>
              </aside>}
              {q && <details className="chat-context"><summary>订单与物料背景</summary><p>订单X需要{run.order.quantity}件成品，A1现有{run.order.a1_available}件；候选替代件A2有{q.physical_available}件可用库存，批次为B17。使用A2还需核对本订单批准及技术条件。</p></details>}
              <div className="wiki-messages">
                {run.messages.map((m, i) => (
                  <article key={i} className={'wiki-message ' + m.role}
                    ref={i === run.messages.length - 1 ? latestAnswer : undefined} tabIndex={-1} aria-label={m.role==='user'?'你的消息':'有界回复'}>
                    <p>{m.role === 'user' ? readableMessage(m.text) : dialogueMessage(m.text)}</p>
                    {m.role !== 'user' && dialogueMessage(m.text) !== m.text && <details><summary>查看判断依据</summary><AnalysisMessage text={m.text}/></details>}
                    {m.documents?.length ? (
                      <small>附带资料：{m.documents.join('、')}</small>
                    ) : null}
                  </article>
                ))}
                {busy==='核对补充信息'&&<>
                  <article className="wiki-message user" aria-label="正在发送的消息"><p>{reply}</p>{attachment&&<small>附带资料：{readableMessage(boot?.sources.find(d=>d.id===attachment)?.title||attachment)}</small>}</article>
                  <article className="wiki-message assistant chat-typing" ref={pendingAnswer} aria-label="有界正在回复"><output aria-label="正在回复"><LoaderCircle className="animate-spin" size={18}/></output></article>
                </>}
              </div>
              {canReply && (
                <div className="wiki-reply">
                  <label htmlFor="reply-preset">快捷回复</label>
                  <NativeSelect id="reply-preset" aria-label="回答示例" value={replyPreset} disabled={!!busy}
                    onChange={(e) => {
                      setReplyPreset(e.target.value);
                      const preset = REPLY_PRESETS.find(p => p.id === e.target.value);
                      setReply(e.target.value === 'clarify' ? '供应商确认：连接件A1预计晚到48小时。' : preset?.text ?? '');
                      setAttachment(preset?.document ?? '');
                    }}>
                    <NativeSelectOption value="custom">自己填写</NativeSelectOption>
                    {run.status === 'needs_input' ? <NativeSelectOption value="clarify">补充物料和延期时间</NativeSelectOption> : REPLY_PRESETS.map(p => <NativeSelectOption key={p.id} value={p.id}>{p.label}</NativeSelectOption>)}
                  </NativeSelect>
                  <label htmlFor="reply-text">
                    回复有界
                  </label>
                  <Textarea
                    id="reply-text"
                    value={busy==='核对补充信息'?'':reply}
                    onChange={(e) => {setReply(e.target.value); setReplyPreset('custom');}}
                    disabled={!!busy}
                    maxLength={6000}
                    placeholder="说说你知道的情况，也可以附上确认材料…"
                  />
                  <label>
                    附带的证明材料（可更换）
                    <NativeSelect
                      aria-label="附加证据"
                      value={attachment}
                      disabled={!!busy}
                      onChange={(e) => setAttachment(e.target.value)}
                    >
                      <NativeSelectOption value="">不附文件</NativeSelectOption>
                      {boot?.sources
                        .filter((d) => !run.active_documents.includes(d.id))
                        .map((d) => (
                          <NativeSelectOption key={d.id} value={d.id}>
                            {readableMessage(d.title)}
                            {boot?.evidence_bundles?.[d.id] ? '（附本订单技术确认）' : ''}
                          </NativeSelectOption>
                        ))}
                    </NativeSelect>
                  </label>
                  {attachment && boot?.sources.filter(d => (boot.evidence_bundles?.[attachment] || [attachment]).includes(d.id)).map(doc => <details key={doc.id}><summary>提交前查看：{readableMessage(doc.title)}</summary><pre className="wiki-source">{doc.body}</pre></details>)}
                  <div className="wiki-actions">
                    <Button
                      disabled={!!busy || !reply.trim()}
                      onClick={() => {
                        setReplyError('');
                        setReplyNotice('');
                        void act('核对补充信息', async () => {
                          try {
                            const result = await request('/reply', {
                              run_id: run.run_id,
                              revision: run.revision,
                              text: reply,
                              document_ids: attachment ? [attachment] : [],
                            });
                            setReplyNotice(result.status === 'model_or_validation_error'
                              ? '补充分析失败，暂未生成方案。输入与附件已保留，请查看下方原因。'
                              : result.status === 'awaiting_approval'
                              ? '补充已处理，已进入恢复方案。'
                              : result.status === 'awaiting_evidence' || result.status === 'needs_input'
                                ? '补充已处理，但还需要信息。请看下面的新回复。'
                                : '补充已处理，请查看下面的结果。');
                            replyResultPending.current = true;
                            showRun(result);
                            navigate('evidence');
                          } catch (e) {
                            setReplyError(e instanceof Error ? e.message : '提交未完成，请稍后重试。');
                            throw e;
                          }
                        });
                      }}
                    >
                      发送
                    </Button>
                    {!busy && !reply.trim() && <small>先选择回答示例，或填写补充内容。</small>}
                  </div>
                  {replyError && <p className="wiki-error" role="alert">本次补充未完成：{replyError}</p>}
                </div>
              )}
              {!canReply && run.status==='awaiting_approval'&&<div className="wiki-actions"><Button onClick={()=>navigate('decision')}>查看恢复方案</Button></div>}
              {!canReply && run.status==='model_or_validation_error'&&<div className="wiki-actions"><Button variant="outline" onClick={()=>navigate('investigate')}>查看本次运行问题</Button></div>}
              {!canReply && run.status === 'paused' && (
                <div className="wiki-note" aria-live="polite">
                  <strong>暂停原因</strong>
                  <p>{run.question}</p>
                  {run.current_hour !== undefined && <p>场景当前第 {run.current_hour} 小时；规划期截至第96小时。</p>}
                  <p>已保留本任务与外部单据，不自动重试或交付。请先核对上述限制；如开始新调查，不得重复下达已存在的工单。</p>
                </div>
              )}
              {q && (
                <details className="wiki-material">
                  <summary>查看已核对的物料数量</summary>
                  <div>
                    <span>A1 已有</span>
                    <strong>{run.order.a1_available} 件</strong>
                  </div>
                  <div>
                    <span>A2 当前物理可用</span>
                    <strong>{q.physical_available} 件</strong>
                  </div>
                  <div>
                    <span>A2 已核验可用</span>
                    <strong>{q.eligible_a2} 件</strong>
                  </div>
                  <div>
                    <span>距需求 {run.order.quantity} 件的物料缺口</span>
                    <strong>{q.shortfall} 件</strong>
                  </div>
                  <p>
                    实际采用批准上限、批次状态与库存中的限制值。不是把 A2
                    库存全部视为合格；是否准时仍需排程。
                  </p>
                </details>
              )}
            </section>
            <aside className="studio-evidence-sources"><h2>判断依据</h2><p>查看本次真正核对过的原始资料。</p>{(run.known_sources||[]).filter(id=>id!=='MAIL-DELAY').map(id=>{const doc=boot?.sources.find(d=>d.id===id);return doc&&<details key={id}><summary><span>{({customer_authority:'客户批准',procurement:'采购沟通',history:'历史处置',engineer:'技术意见',quality:'质量记录'} as Record<string,string>)[doc.role]||'来源资料'}</span><strong>{readableMessage(doc.title)}</strong></summary>{activeWiki?.claims.filter(c=>c.citation.document_id===id).map((c,i)=><blockquote key={i}>{c.citation.quote}</blockquote>)}<pre>{doc.body}</pre></details>;})}{!run.known_sources?.length&&<p>尚未取得资料查询结果。</p>}<Button variant="outline" onClick={()=>navigate('knowledge')}>打开完整知识库目录</Button></aside>
          </div>
          {stage==='decision' && !!run.plans.length && (
            <section id="plan-comparison" tabIndex={-1} className="wiki-section">
              <h2>同一订单，三种取舍</h2>
              {run.supply_offers&&<details className="studio-offers"><summary>查看本次供货调查</summary><div>{run.supply_offers.offers.map(o=><article key={o.source}><strong>{o.source}</strong><p>第{o.arrival_hour}小时到货 · 追加¥{o.incremental_unit_cost}/件</p></article>)}</div></details>}
              {!run.execution && <div className="harness-budget"><label htmlFor="decision-budget">折中方案预算（元）</label><Input id="decision-budget" type="number" min={0} max={9600} key={`${run.run_id}-${run.revision}`} defaultValue={run.decision_budget??400} />
                <Button disabled={!!busy || run.runtime_compatible===false} onClick={()=>act('按新预算重新求解',async()=>{
                  const input=document.getElementById('decision-budget') as HTMLInputElement;
                  const updated=await request('/constraints/budget',{run_id:run.run_id,revision:run.revision,budget:Number(input.value)});
                  showRun(updated,updated.status==='awaiting_approval'?'decision':stageForRun(updated));
                })}>{busy==='按新预算重新求解'?'正在重新比较…':'按这个预算重新比较'}</Button></div>}
              {run.a1_quarantine_event && <aside className="wiki-event-result" aria-live="polite">
                <strong>仓库复检隔离了 {run.a1_quarantine_event.quantity} 个A1，已重新计算</strong>
                <p>A1可用量从 {run.a1_quarantine_event.previous_a1} 降到 {run.a1_quarantine_event.remaining_a1} 个；现需补齐 {q?.shortfall} 个。旧方案和审批已失效，请重新选择。模拟仓库事件，没有修改ERP真实库存。</p>
                {!!q?.shortfall && q.shortfall * 3 > (run.decision_budget??400) && <p>区域调拨补齐缺口需要 ¥{q.shortfall * 3}，超过当前{run.decision_budget??400}元预算；预算方案不会擅自超支。</p>}
              </aside>}
              <div className="wiki-table-wrap"><table><caption>订单 X：原交期第12小时 · 数量 {run.order.quantity} 件</caption>
                <thead><tr><th>策略</th><th>追加成本</th><th>缺口如何补齐</th><th>完工</th><th>延期</th><th>核验</th></tr></thead>
                <tbody>{run.plans.map(({plan,summary})=><tr key={plan.plan_id}><th>{PROFILES[plan.profile]}</th><td>¥{summary.recovery_cost}</td>
                  <td>{purchaseDescription(plan.purchases)}</td>
                  <td>{plan.order_outcomes[0]?.completion_hour == null ? '未排入' : `${plan.order_outcomes[0].completion_hour} h`}</td><td>{plan.order_outcomes[0]?.scheduled ? plan.order_outcomes[0].late_hours : '未排入，不能计为零延期'}{plan.order_outcomes[0]?.scheduled ? ' h' : ''}</td>
                  <td>{plan.evidence?.verified ? (plan.order_outcomes[0]?.scheduled ? '整单已排入' : '仅不交付解，不能执行恢复') : '未核验，不可批准'}</td></tr>)}</tbody></table></div>
              <figure className="wiki-comparison" aria-label="三方案共享时间轴，0到96小时">
                <div className="wiki-time-legend">
                  <span className="due">原交期 12h</span>
                  <span className="normal">正常补货 {8 + run.order.delay_hours}h</span>
                  <span className="emergency">应急到货 8h（仅采购时采用）</span>
                  <span className="regional">区域调拨 24h（仅采用时）</span>
                  <span className="production">实线条：生产</span>
                  <span className="late">斜纹区：交期至完工的延期</span>
                </div>
                <div className="wiki-time-ticks" aria-hidden="true"><span>0h</span><span>24h</span><span>48h</span><span>72h</span><span>96h</span></div>
                {run.plans.map(({plan, summary}) => {
                  const outcome = plan.order_outcomes[0];
                  const completion = outcome?.completion_hour;
                  const scheduled = outcome?.scheduled && completion != null;
                  return <div className="wiki-time-row" key={plan.plan_id}>
                    <strong>{PROFILES[plan.profile]} · ¥{summary.recovery_cost}</strong>
                    <div className="wiki-time-track" aria-hidden="true">
                      {scheduled && completion > 12 && <span className="wiki-time-late" style={{left:'12.5%', width:`${(completion-12)/96*100}%`}} />}
                      <i className="normal" style={{left:`${(8+run.order.delay_hours)/96*100}%`}} />
                      <i className="emergency" style={{left:`${8/96*100}%`}} />
                      <i className="regional" style={{left:'25%'}} />
                      <i className="due" style={{left:'12.5%'}} />
                      {plan.scheduled_operations.map((op, index) => <span className="wiki-time-production" key={index} style={{left:`${op.start_hour/96*100}%`,width:`${(op.end_hour-op.start_hour)/96*100}%`}} />)}
                    </div>
                    <p>{scheduled ? <>生产 {plan.scheduled_operations.map(op=>`${op.start_hour}–${op.end_hour}h`).join('、')}；完工 {completion}h；比原交期晚 {outcome.late_hours}h</> : '未排入生产：没有可执行的恢复窗口，不能把延期记为0。'}</p>
                  </div>;
                })}
              </figure>
              <div className="wiki-plan-grid">
                {run.plans.map(({ plan, summary }) => (
                  <article key={plan.plan_id} className="wiki-plan">
                    <h3>{PROFILES[plan.profile]}</h3>
                    <p>{purchaseDescription(plan.purchases)}</p>
                    {plan.profile === 'balanced' && summary.recovery_cost === 0 && plan.order_outcomes[0]?.scheduled && plan.order_outcomes[0].late_hours > 0 && run.plans.some(other => other.plan.profile === 'stability_first' && other.summary.recovery_cost === summary.recovery_cost && other.plan.order_outcomes[0]?.completion_hour === plan.order_outcomes[0]?.completion_hour) && <p>本次{run.decision_budget??400}元预算内没有更快的完整交付方案，因此与“不追加成本”方案相同。</p>}
                    <dl>
                      <div>
                        <dt>追加成本</dt>
                        <dd>¥{summary.recovery_cost}</dd>
                      </div>
                      <div>
                        <dt>完工时间</dt>
                        <dd>
                          {plan.order_outcomes[0]?.completion_hour == null ? '未排入' : `${plan.order_outcomes[0].completion_hour} 小时`}
                        </dd>
                      </div>
                      <div>
                        <dt>延期</dt>
                        <dd>{plan.order_outcomes[0]?.scheduled ? `${plan.order_outcomes[0].late_hours} 小时` : '未排入，延期尚无有效结果'}</dd>
                      </div>
                      <div>
                        <dt>按时交付</dt>
                        <dd>{summary.first_due_on_time_units} 件</dd>
                      </div>
                    </dl>
                    <Button
                      disabled={
                        !!busy ||
                        run.runtime_compatible === false ||
                        run.status !== 'awaiting_approval' ||
                        !plan.evidence?.verified ||
                        !plan.order_outcomes.length ||
                        plan.order_outcomes.some(outcome => !outcome.scheduled) ||
                        !actor.trim()
                      }
                      onClick={() =>
                        act('确认本地方案', async () =>
                          showRunWithNavigation(
                            await request('/approve', {
                              run_id: run.run_id,
                              revision: run.revision,
                              plan_id: plan.plan_id,
                              actor,
                            }),
                          ),
                        )
                      }
                    >
                      批准方案（交付需再确认）
                    </Button>
                  </article>
                ))}
              </div>
              <label className="wiki-actor" htmlFor="plan-actor">
                审批人姓名（必填，用于批准记录）
                <Input
                  id="plan-actor"
                  aria-label="审批人姓名"
                  required
                  placeholder="填写本次批准人姓名"
                  value={actor}
                  onChange={(e) => setActor(e.target.value)}
                  maxLength={80}
                />
              </label>
              {run.case_id !== 'guided' && <div className="wiki-actions">
                <Button
                  variant="outline"
                  disabled={!!busy || run.runtime_compatible === false || run.stock.hold === 200 || !!run.execution || !['awaiting_approval','approved_local_drafts'].includes(run.status)}
                  onClick={() =>
                    act('核对模拟库存回流', async () =>
                      showRun(
                        await request('/feedback', {
                          run_id: run.run_id,
                          revision: run.revision,
                          hold: 200,
                        }),
                      ),
                    )
                  }
                >
                  模拟冻结总量改为200件并重算
                </Button>
                <span>明确模拟质量事件，不冒充真实 MES 回报。</span>
              </div>}
            </section>
          )}
          {stage==='execution' && (run.plans.length > 0 || run.execution || run.capacity_event) && <FinalsExecutionPanel
            enabled={!!boot?.external_enabled}
            busy={!!busy || run.runtime_compatible === false}
            actor={actor}
            run={run}
            onViewPlans={()=>navigate('decision')}
            onAction={(path, extra) =>
              act('核对真实测试系统', async () => {
                  const updated=await request(path, {
                    run_id: run.run_id,
                    revision: run.revision,
                    ...extra,
                  });
                  if(path==='/feedback/capacity-replan') showRun(updated,stageForRun(updated));
                  else showRunWithNavigation(updated);
              })
            }
          />}
            <details hidden={stage!=='knowledge'} id="knowledge-evidence" className="wiki-section wiki-evidence">
              <summary>本次已核对资料与知识整理（按需查阅）</summary>
              <h2>
                <BookOpen size={20} /> 原始资料与知识整理
              </h2>
              <p>
                原文优先。历史案例、采购说法、客户批准和质量放行分别保留，不合并成一句“可以用”。
              </p>
              <small>
                当前构建：
                {activeWiki?.mode === 'live'
                  ? '在线模型选择原文片段＋程序字段核验'
                  : '来源字段编译（不是模型生成）'}
              </small>
              {activeWiki?.conflicts.map((c, i) => (
                <div className="wiki-conflict" key={i}>
                  <strong>
                    {c.kind === 'same_scope_conflict'
                      ? '同范围冲突，待核对'
                      : '泛化说法，待核实'}
                  </strong>
                  <p>{c.message}</p>
                  <small>{c.sources.join(' / ')}</small>
                </div>
              ))}
              {activeWiki?.claims.filter(c => c.citation.document_id !== 'MAIL-DELAY' && run.known_sources?.includes(c.citation.document_id)).map((c, i) => (
                <article className="wiki-claim" key={i}>
                  <details>
                    <summary>{c.citation.document_id === 'MAIL-DELAY' ? '旧版24小时延期邮件样例（非本次输入）' : boot?.sources.find(d => d.id === c.citation.document_id)?.title || c.citation.document_id} · 查看原文</summary>
                    {c.citation.document_id === 'MAIL-DELAY' && <p>这是保留的固定演示资料，不是本次供应商通知。本次延期以本任务输入和订单分析结果为准。</p>}
                    <pre className="wiki-source">{boot?.sources.find(d => d.id === c.citation.document_id)?.body}</pre>
                  </details>
                  <p>{c.summary}</p>
                  {c.untrusted_model_summary && (
                    <small>模型选择的原文片段，不授予业务权限。</small>
                  )}
                  <details>
                    <summary>引用与版本</summary>
                    <blockquote>{c.citation.quote}</blockquote>
                    <code>
                      字符 {c.citation.start}–{c.citation.end}
                      <br />
                      {c.citation.source_hash}
                    </code>
                  </details>
                </article>
              ))}
            </details>
          <details hidden={stage!=='audit'} className="wiki-section">
            <summary>查看技术记录与实际查询过程</summary>
            <p>模型：{run.mode === 'live' ? run.model_name : '离线规则'}；模型尝试{run.model_calls}次，工具查询{run.tool_calls}次，任务版本{run.revision}。</p>
            <h2>
              <GitBranch size={20} /> 本次实际调查路径
            </h2>
            <div className="wiki-path">
              {run.trace
                .filter((t) => t.tool)
                .map((t) => (
                  <span key={t.sequence}>
                    第{t.turn}轮 · {TOOLS[t.tool!]}
                  </span>
                ))}
            </div>
            <details>
              <summary>展开逐步依据及工具返回</summary>
              {run.trace.map((t) => (
                <div className="wiki-trace" key={t.sequence}>
                  <strong>
                    {t.sequence}. {t.node}
                  </strong>
                  <p>{t.message}</p>
                  <pre>{JSON.stringify(t, null, 2)}</pre>
                </div>
              ))}
            </details>
          </details>
        </>
      ) : (
        <section hidden={stage!=='evidence'} className="wiki-empty">
          <BookOpen size={26} />
          <h2>选好消息，点击“分析这次延期”即可</h2>
          <p>
            系统会先核对订单、库存和历史资料。如果缺少证明，会具体告诉你缺什么；补齐后才会给出成本与交期比较。
          </p>
          <p>资料齐全则直接进入方案。缺证据时继续补充，你也可以要求暂停。</p>
        </section>
      )}
      {stage==='decision' && !run?.plans.length && <section id="plan-comparison" className="wiki-section"><h2>尚未生成可比较的方案</h2><p>{run ? `当前：${STATES[run.status] || run.status}。` : '等待开始分析。'}核对通过后，展示成本、延期及甘特图。</p><Button onClick={()=>navigate(run?'evidence':'intake')}>{run ? '回到核对与补充' : '先分析供应商消息'}</Button></section>}
      <details hidden={stage!=='audit'} className="wiki-section" aria-label="高级验证" open>
        <summary>高级验证：方法对比与分析记录（正常体验无需操作）</summary>
        <h3>方法对比用来验证什么？</h3>
        <p>动态方法根据缺失信息选择下一步，固定方法按预设顺序查询。这里会用上方当前消息和资料设置，加上两条固定的测试回复，额外运行两条离线规则流程，对比状态、查询次数和顺序。两条回复只是对照样例，不是主流程的补证上限；它也不是当前任务回放或真实模型对比，不会改变主流程结果或发送工单。</p>
        <Button variant="outline" disabled={!!busy || !boot || !text.trim()}
          onClick={() => act('执行离线对照', async () => setComparison(await request('/compare', {text, case_id: caseId, mode: 'offline_rules'})))}>
          运行方法对比（离线规则）
        </Button>
      {comparison && (
        <section className="wiki-section">
          <h2>同输入、同证据的真实离线对照</h2>
          <p>{comparison.disclosure}</p>
          <div className="wiki-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>策略</th>
                  <th>终态</th>
                  <th>工具调用</th>
                  <th>模型调用</th>
                  <th>人工补充</th>
                  <th>A2 获准数量</th>
                </tr>
              </thead>
              <tbody>
                {comparison.runs.map((r) => (
                  <tr key={r.policy}>
                    <td>{r.policy === 'fixed' ? '固定顺序' : '按缺口调查'}</td>
                    <td>{STATES[r.status]}</td>
                    <td>{r.tool_calls}</td>
                    <td>{r.model_calls}</td>
                    <td>{r.reply_count}</td>
                    <td>{r.qualification?.eligible_a2 ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details>
            <summary>查看两种策略的实际调用顺序</summary>
            {comparison.runs.map((r) => (
              <p key={r.policy}>
                {r.policy}：
                {r.trace
                  .filter((t) => t.tool)
                  .map((t) => TOOLS[t.tool!])
                  .join(' → ')}
              </p>
            ))}
          </details>
        </section>
      )}

        {run && <><h3>开发验证：重新整理资料摘要</h3><p>分析与补充资料时已经自动整理。此操作只重新整理摘要，不会批准物料或生成恢复方案，正常体验无需点击。</p>
              <Button
                variant="outline"
                disabled={!!busy || run.runtime_compatible === false}
                onClick={() =>
                  act('整理当前知识库', async () => {
                    const result = await request('/wiki', {
                      run_id: run.run_id,
                      revision: run.revision,
                    });
                    setRun(result);
                    setWiki(result.wiki);
                  })
                }
              >
                重新整理知识库{run.mode === 'live' ? '（调用模型）' : ''}
              </Button>
        </>}
        <h3>分析记录是什么？</h3>
        <p>记录包含本次输入、引用资料、查询过程、方案和状态，供技术复核。下载不会批准方案，也不会发送工单；JSON是机器可读文件，普通体验无需下载。</p>
        {!run && <p>完成一次分析后，才会提供这次分析的下载记录。</p>}
      {run && (
        <Button
          variant="outline"
          disabled={!!busy || !boot}
          onClick={() => act('导出本机任务证据', async () => {
            const response = await fetch(`${API}/runs/${run.run_id}/evidence`, {
              headers: {'X-Youjie-Session': sessionCapability},
            });
            const result = await response.json();
            if (!response.ok) {
              const message = typeof result === 'object' && result !== null &&
                'message' in result && typeof result.message === 'string'
                ? result.message : '证据导出失败';
              throw new Error(message);
            }
            const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type:'application/json'}));
            const link = document.createElement('a');
            link.href = url;
            link.download = `${run.run_id}-evidence.json`;
            link.click();
            window.setTimeout(() => URL.revokeObjectURL(url), 1000);
          })}
        >下载本次分析记录（JSON）</Button>
      )}

      </details>
    </main>
    </FinalsStudio>
  );
}
