"""Three same-run live-model and real-instance tests. No stock posting or WO submit."""
import argparse
import json
import subprocess
from pathlib import Path
from delivery_guard.finals_api import FinalsApplication
from delivery_guard.finals_live import FinalsLiveModel
from delivery_guard.integration import (ERPNextConfig,ERPNextHttpClient,ERPNextAdapter,ERPNextExecutionLedger,
    OpenMESConfig,OpenMESHttpClient,OpenMESAdapter,OpenMESExecutionLedger)
from delivery_guard.integration.finals_execution import FinalsExecution
from delivery_guard.integration.finals_state import FinalsStateStore

ROOT=Path(__file__).resolve().parents[1]
ACTOR='Codex operator / user-authorized local test'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--erp-credential-file',type=Path,required=True)
    p.add_argument('--mes-credential-file',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--guided-only',action='store_true',help='Run the current 48h / 300-A2 guided UI case only')
    p.add_argument('--mcp',action='store_true',help='Use actual stdio MCP for test-instance HTTP operations')
    p.add_argument('--operator-button',action='store_true',help='Exercise the explicit operator-event API used by the UI')
    p.add_argument('--plan-profile', choices=['service_first','balanced','stability_first'], default='service_first')
    args=p.parse_args()
    if args.output.exists(): p.error('Preserve previous evidence')
    store=FinalsStateStore(ROOT/'.tmp/finals_v2/runs')
    erp=ERPNextAdapter(ERPNextHttpClient(ERPNextConfig.from_environment({'DELIVERY_GUARD_ERPNEXT_CREDENTIAL_FILE':str(args.erp_credential_file)})),ledger=ERPNextExecutionLedger(ROOT/'.tmp/erpnext_execution.sqlite3'))
    mes=OpenMESAdapter(OpenMESHttpClient(OpenMESConfig.from_environment({'DELIVERY_GUARD_OPENMES_CREDENTIAL_FILE':str(args.mes_credential_file)})),ledger=OpenMESExecutionLedger(ROOT/'.tmp/openmes_execution.sqlite3'))
    if args.mcp:
        from delivery_guard.finals_mcp import EnterpriseMCPClient
        erp.client=EnterpriseMCPClient(erp.client.config,args.erp_credential_file,'erp')
        mes.client=EnterpriseMCPClient(mes.client.config,args.mes_credential_file,'mes')
    mapping=json.loads((ROOT/'data/integrations/finals_v2_mapping.json').read_text())
    service=FinalsExecution(erp,mes,mapping,store.save)
    model=FinalsLiveModel(operator_token_plan=True)
    app=FinalsApplication(live_model=model,store=store,execution=service)
    report={'complete':False,'rows':[],'simulation':'Business data and operator-produced quantity are synthetic; software and HTTP adapters are real',
            'native_work_order_submission':False,'stock_posting':False}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    cases = [('guided_partial',600,True,False)] if args.guided_only else [('main',600,True,False),('quantity_variant',400,False,False),('lost_mes_response',600,False,True)]
    for label,quantity,two_replies,fault in cases:
        row={'label':label,'quantity':quantity,'passed':False}
        report['rows'].append(row);save()
        state=None
        try:
            state=app.post('/start',{'text':'连接件A1预计比原定到货时间晚48小时。' if args.guided_only else f'A1延期24小时，订单需要{quantity}件，请调查替代依据并给出恢复方案。',
                'case_id':'guided' if args.guided_only else 'two_reply' if two_replies else 'ready','mode':'live','policy':'adaptive'})
            row['run_id']=state['run_id'];save()
            def post(path,**fields):
                return app.post(path,{'run_id':state['run_id'],'revision':state['revision'],**fields})
            if two_replies:
                assert state['status']=='awaiting_evidence'
                state=post('/reply',text='王工说没问题，你核对一下',document_ids=[])
                assert state['status']=='awaiting_evidence'
                state=post('/reply',text='找到本订单的技术确认和客户批准,允许使用300个A2,请核对附件。' if args.guided_only else '附上本订单的客户批准和技术附件，请核验后排程',document_ids=['AP-PARTIAL' if args.guided_only else 'AP-CURRENT','TECH-CURRENT'])
            assert state['status']=='awaiting_approval'
            if args.guided_only:
                assert state['order']['quantity']==600 and state['qualification']['eligible_a2']==300
                assert state['plans'][0]['summary']['recovery_cost']==800
                assert 'MAIL-DELAY' not in state['active_documents'] and 'MAIL-DELAY' not in state['known_sources']
            state=post('/wiki')
            chosen = next(row for row in state['plans'] if row['plan']['profile'] == args.plan_profile)
            row['selected_profile'] = args.plan_profile
            row['selected_cost'] = chosen['summary']['recovery_cost']
            row['selected_purchases'] = chosen['plan']['purchases']
            state=post('/approve',plan_id=chosen['plan']['plan_id'],actor=ACTOR)
            original=mes.execute
            if fault:
                def lost(command):
                    original(command)
                    raise TimeoutError('Deliberate operator test: reply lost after actual MES import')
                mes.execute=lost
            try:
                state=post('/integrations/execute',actor=ACTOR,confirmed=True)
            except TimeoutError:
                if not fault: raise
                state=store.load(state['run_id'])
                row['uncertain_status']=state['execution']['status']
                assert row['uncertain_status']=='mes_outcome_unknown'
            finally: mes.execute=original
            if fault:
                # Fresh application instance demonstrates persisted-state recovery.
                app=FinalsApplication(live_model=model,store=store,execution=service)
                state=post('/integrations/reconcile')
            assert state['execution']['status']=='monitoring'
            first=state['execution']['erp_document']['name']
            state=post('/integrations/execute',actor=ACTOR,confirmed=True)
            assert state['execution']['erp_document']['name']==first
            row['initial_evidence']=app.evidence(state['run_id']);save()
            if args.operator_button:
                state=post('/feedback/demo-progress',actor=ACTOR,confirmed=True)
                row['operator_event']=state['execution']['operator_demo']
            else:
                output=subprocess.run(['docker','exec','-i','youjie_openmes-backend','php','--',state['run_id'],first],
                    input=(ROOT/'scripts/finals_mes_operator_event.php').read_bytes(),capture_output=True,check=True)
                row['operator_event']=json.loads(output.stdout)
                state=post('/feedback/poll')
            assert state['status']=='needs_reconciliation' and state['approval'] is None
            event=state['pending_execution_event']
            state=post('/feedback/confirm',event_id=event['event_id'],actor=ACTOR,
                evidence_ref=f'operator_event:{event["event_id"]}; synthetic good/consumption assumption',
                good_qty=100,a1_consumed=100,a2_consumed=0,elapsed_hours=2)
            assert state['order']['quantity']==quantity-100 and state['completed_good']==100
            assert state['order']['a1_available']==100 and state['status']=='awaiting_approval'
            rows=erp.client.list_documents('Work Order',fields=['name'],filters=[['description','like',f'%run={state["run_id"]} %']])
            assert len(rows)==1
            state=post('/approve',plan_id=state['plans'][0]['plan']['plan_id'],actor=ACTOR)
            try: post('/integrations/execute',actor=ACTOR,confirmed=True)
            except ValueError as exc: assert 'NO_DUPLICATE' in str(exc)
            else: raise AssertionError('Duplicate remaining order was allowed')
            row.update(passed=True,erp_order=first,remaining=quantity-100,final_evidence=app.evidence(state['run_id']))
        except Exception as exc:
            row['error']={'type':type(exc).__name__,'code':getattr(exc,'code',str(exc) if isinstance(exc,(ValueError,AssertionError)) else 'CHECK_ERROR')}
            if state is not None: row['failed_evidence']=app.evidence(state['run_id'])
            save();raise
        save();print(label,'passed',first,flush=True)
    report['complete']=True;report['passed']=all(r['passed'] for r in report['rows']);save()

if __name__=='__main__': main()
