// Pure view-routing regression; no browser, model or ERP/MES calls.
import assert from 'node:assert/strict';
import {stageForRun,stageAfterAnalysis} from '../frontend/site/lib/finals-stage.ts';
const cases=[
 [{status:'awaiting_evidence'},'evidence'],
 [{status:'needs_input'},'evidence'],
 [{status:'awaiting_approval',plans:[1]},'decision'],
 [{status:'awaiting_approval',plans:[1],execution:{status:'monitoring'},external_followup:'manual'},'decision'],
 [{status:'needs_reconciliation',execution:{status:'monitoring'}},'execution'],
 [{status:'approved_local_drafts'},'execution'],
 [{status:'model_or_validation_error',plans:[1]},'investigate'],
 [{status:'model_or_validation_error',execution:{status:'erp_outcome_unknown'}},'execution'],
 [{status:'approved_local_drafts',execution:{status:'partial_failure'}},'execution'],
 [{status:'awaiting_approval',runtime_compatible:false},'investigate'],
 [{status:'paused'},'evidence'],
 [{status:'no_disruption'},'evidence'],
 [{status:'completed'},'execution'],
];
for(const [run,expected] of cases){const before=JSON.stringify(run);assert.equal(stageForRun(run),expected);assert.equal(JSON.stringify(run),before);}
console.log(`${cases.length} stage routing checks passed; no state mutations`);
for(const [run,expected] of cases)assert.equal(stageAfterAnalysis(run),expected==='execution'?'execution':'investigate');
console.log(`${cases.length} analysis-stop checks passed; explicit user navigation required`);
