'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export type ExecutionDetails = {
  status: string;
  operator_demo?: {status:string};
  erp_document?: {
    name: string;
    qty: number;
    required_items: Array<{ item_code: string; required_qty: number }>;
  };
  mes_baseline?: {
    records: Array<{
      order_no: string;
      status: string;
      planned_qty: number;
      produced_qty: number;
    }>;
  };
  last_poll?: { changed: boolean };
  last_error?: { code: string };
};
type Action = '/integrations/execute' | '/integrations/reconcile' | '/feedback/poll' | '/feedback/confirm' | '/feedback/demo-progress' | '/feedback/capacity' | '/feedback/capacity-replan';
type Props = {
  onViewPlans?: () => void;
  enabled: boolean;
  busy: boolean;
  actor: string;
  run: {
    status: string;
    capacity_event?: {status:string;start_hour?:number;end_hour?:number};
    execution?: ExecutionDetails;
    external_followup?: string;
    pending_execution_event?: {
      event_id: string;
      produced_qty: number;
      order_no: string;
    };
  };
  onAction: (path: Action, extra: Record<string, unknown>) => void;
};

export function FinalsExecutionPanel({
  enabled,
  busy,
  actor,
  run,
  onAction,
  onViewPlans,
}: Props) {
  const [good, setGood] = useState('100');
  const [a1, setA1] = useState('100');
  const [a2, setA2] = useState('0');
  const [hour, setHour] = useState('2');
  const [evidence, setEvidence] = useState('');
  const e = run.execution;
  const labels: Record<string, string> = {
    monitoring: '两系统已回读，等待执行反馈',
    erp_verified: 'ERP已回读，MES待交付',
    partial_failure: '部分完成，不重复ERP建单',
    erp_outcome_unknown: 'ERP响应未确认，禁止盲重试',
    mes_outcome_unknown: 'MES响应未确认，禁止盲重试',
  };
  return (
    <section id="execution-delivery" tabIndex={-1} className="wiki-section" aria-label="真实测试系统交付与执行回流">
      <h2>生产任务与执行进度</h2>
      {!e&&!run.capacity_event&&run.status==='approved_local_drafts'&&<div className="wiki-event-drill">
        <h3>交付前，试一次现场变化</h3>
        <Button variant="outline" disabled={busy||!enabled||!actor.trim()} onClick={()=>onAction('/feedback/capacity',{actor,confirmed:true})}>手动注入变更：产线被占用32小时</Button>
      </div>}
      {run.capacity_event&&<div className="wiki-event-result" aria-live="polite">
        <strong>{run.status==='capacity_changed'?'旧方案与审批已失效':'已纳入产线占用变化'}</strong>
        <p>{run.capacity_event.status==='readback_verified'?'MES已回读：产线第0—32小时被其他任务占用。':'MES变更尚未核实，已阻止交付。'}</p>
        {run.status==='capacity_changed'&&<Button disabled={busy||run.capacity_event.status!=='readback_verified'} onClick={()=>onAction('/feedback/capacity-replan',{})}>重新计算恢复方案</Button>}
      </div>}
      <div className="wiki-actions">
        <Button
          disabled={
            busy ||
            !enabled ||
            run.status !== 'approved_local_drafts' ||
            !!run.external_followup ||
            !!e ||
            !actor.trim()
          }
          onClick={() =>
            onAction('/integrations/execute', { actor, confirmed: true })
          }
        >
          {e?'本任务已交付，请查看回读记录':'确认方案，发送到测试业务系统'}
        </Button>
        <Button
          variant="outline"
          disabled={busy || !enabled || e?.status !== 'monitoring'}
          onClick={() => onAction('/feedback/poll', {})}
        >
          查看最新生产进度
        </Button>
        <a href="http://127.0.0.1:8088/desk" target="_blank" rel="noreferrer">
          打开 ERPNext
        </a>
        <a href="http://127.0.0.1:8090" target="_blank" rel="noreferrer">
          打开 OpenMES
        </a>
      </div>
      {e && (
        <output className="studio-execution-status">
          {run.status === 'needs_reconciliation'
            ? '旧方案与审批已失效 · MES 执行状态已变化'
            : run.status === 'paused' && run.external_followup
              ? '原单据保留；当前恢复计划暂停，不会自动交付'
              : labels[e.status] || e.status}
          {e.last_poll?.changed === false ? '；本次检查无业务变化' : ''}
        </output>
      )}
      {e?.last_error && (
        <p className="wiki-error">
          执行未完成：{e.last_error.code}
          。保留已创建单号；不要重新创建整个任务来重试。
        </p>
      )}
      {e && ['erp_outcome_unknown','mes_outcome_unknown','partial_failure'].includes(e.status) && <Button variant="outline" disabled={busy} onClick={()=>onAction('/integrations/reconcile',{})}>只读核对远端结果（不重新下单）</Button>}
      {e?.erp_document && (
        <div className="wiki-table-wrap">
          <table>
            <caption>
              ERP 实际回读 · {e.erp_document.name} · 成品 {e.erp_document.qty}{' '}
              件
            </caption>
            <thead>
              <tr>
                <th>真实物料代码</th>
                <th>所需数量</th>
              </tr>
            </thead>
            <tbody>
              {e.erp_document.required_items.map((r) => (
                <tr key={r.item_code}>
                  <td>{r.item_code}</td>
                  <td>{r.required_qty}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {e?.mes_baseline?.records.map((r) => (
        <p key={r.order_no}>
          MES 上次已确认基线 · 同号工单 {r.order_no}：计划 {r.planned_qty}，已报产{' '}
          {r.produced_qty}，状态 {r.status}。
        </p>
      ))}
      <section id="execution-feedback" tabIndex={-1} style={{marginTop:28,paddingTop:20,borderTop:'1px solid #cbdedd'}}>
      {run.status === 'needs_reconciliation' && run.pending_execution_event && (
        <details className="wiki-reply">
          <summary>核对现场并重新计算</summary>
          <p>
            MES 本次新增报产 {run.pending_execution_event.produced_qty}{' '}
            件。请确认合格量与耗料，再计算剩余计划。
          </p>
          <div className="wiki-controls">
            <label htmlFor="execution-good">
              确认合格数量
              <Input
                id="execution-good"
                type="number"
                min="0"
                value={good}
                onChange={(x) => setGood(x.target.value)}
              />
            </label>
            <label htmlFor="execution-a1">
              A1 已消耗
              <Input
                id="execution-a1"
                type="number"
                min="0"
                value={a1}
                onChange={(x) => setA1(x.target.value)}
              />
            </label>
            <label htmlFor="execution-a2">
              A2 已消耗
              <Input
                id="execution-a2"
                type="number"
                min="0"
                value={a2}
                onChange={(x) => setA2(x.target.value)}
              />
            </label>
            <label htmlFor="execution-hour">
              场景当前小时
              <Input
                id="execution-hour"
                type="number"
                min="0"
                max="95"
                value={hour}
                onChange={(x) => setHour(x.target.value)}
              />
            </label>
          </div>
          <label htmlFor="execution-evidence">
            对账依据（必填，明确为测试人员确认）
            <Input
              id="execution-evidence"
              value={evidence}
              onChange={(x) => setEvidence(x.target.value)}
              placeholder="例如：本次测试人工核对记录，100件合格、领用A1 100件"
            />
          </label>
          <Button
            disabled={
              busy ||
              !evidence.trim() ||
              !actor.trim() ||
              [good, a1, a2, hour].some((v) => !/^\d+$/.test(v))
            }
            onClick={() =>
              onAction('/feedback/confirm', {
                event_id: run.pending_execution_event!.event_id,
                actor,
                evidence_ref: evidence,
                good_qty: Number(good),
                a1_consumed: Number(a1),
                a2_consumed: Number(a2),
                elapsed_hours: Number(hour),
              })
            }
          >
            确认测试对账，计算剩余计划
          </Button>
        </details>
      )}
      {run.external_followup && (
        <p className="wiki-note">
          {run.status === 'paused'
            ? '旧审批已失效；当前没有可批准的剩余计划。须先解决暂停原因，再重新核验。'
            : '旧审批已失效；剩余计划待重新审批及人工落实。'}
          现有工单未自动撤销或改写，也不会重复下发完整订单。
        </p>
      )}
      {run.external_followup && onViewPlans && <Button variant="outline" onClick={onViewPlans}>查看新方案</Button>}
      </section>
    </section>
  );
}
