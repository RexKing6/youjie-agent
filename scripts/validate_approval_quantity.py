"""Operator-run live synthetic regression, no external business writes or retries."""
import json
from pathlib import Path
from datetime import datetime
from delivery_guard.finals_agent import FinalsInvestigation
from delivery_guard.finals_live import FinalsLiveModel

root = Path(__file__).resolve().parents[1]
out = root/'artifacts/finals_v2'/('approval_quantity_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
out.mkdir(parents=True, exist_ok=False)
text = '找到本订单的技术确认和客户批准,允许使用300个A2,请核对附件。'
cases = [(text, ['AP-PARTIAL', 'TECH-CURRENT'])]*2 + [
    ('这份邮件批准本单使用300件A2，技术确认也一起补上，请核对。', ['AP-PARTIAL', 'TECH-CURRENT']),
    (text, [])]
rows = []
for i,(reply, documents) in enumerate(cases):
    engine = FinalsInvestigation(model=FinalsLiveModel(operator_token_plan=True))
    run = engine.start('连接件A1预计比原定到货时间晚48小时。', case_id='guided')
    if run['status'] == 'awaiting_evidence':
        run = engine.reply(run['run_id'], run['revision'], reply, documents)
    good = (run['status'] == 'awaiting_approval' and run['qualification']['eligible_a2'] == 300
            and len(run['plans']) == 3 and all(p['plan']['evidence']['verified'] for p in run['plans'])) if documents else (
            run['status'] in ('awaiting_evidence','paused') and not run['plans'] and run['qualification']['eligible_a2'] == 0)
    good = good and run['order']['quantity'] == 600 and not run['approval'] and not run['drafts']
    (out/f'run_{i+1}.json').write_text(json.dumps(run, ensure_ascii=False, indent=2))
    rows.append({'case':i+1,'status':run['status'],'passed':good,'calls':run['model_calls']})
    (out/'report.json').write_text(json.dumps({'kind':'live development regression','results':rows,'complete':len(rows)==4},indent=2))
    print(rows[-1], flush=True)
print(out, flush=True)
raise SystemExit(0 if all(r['passed'] for r in rows) else 1)
