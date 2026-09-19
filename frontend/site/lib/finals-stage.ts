export type StudioStage = 'intake'|'investigate'|'evidence'|'decision'|'execution'|'knowledge'|'skills'|'audit';
type State = {status:string;runtime_compatible?:boolean;external_followup?:string;plans?:unknown[];execution?:{status:string}};
export function stageAfterAnalysis(run:State):StudioStage {
  return stageForRun(run)==='execution'?'execution':'investigate';
}
export function stageForRun(run:State):StudioStage {
  if(run.status==='capacity_changed') return 'execution';
  if(run.execution && ['erp_outcome_unknown','mes_outcome_unknown','partial_failure'].includes(run.execution.status)) return 'execution';
  if(run.status==='needs_reconciliation') return 'execution';
  if(run.status==='model_or_validation_error'||run.runtime_compatible===false) return 'investigate';
  if(['needs_input','awaiting_evidence','paused','no_disruption'].includes(run.status)) return 'evidence';
  if(run.status==='awaiting_approval') return 'decision';
  if(run.execution||run.status==='approved_local_drafts'||run.status==='completed') return 'execution';
  return run.plans?.length?'decision':'investigate';
}
