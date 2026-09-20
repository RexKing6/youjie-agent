"""Export one verified recorded demo to a credential-free browser fixture."""
import hashlib
import json
from pathlib import Path
import re
from delivery_guard.integration.finals_state import FinalsStateStore
from delivery_guard.finals_api import FinalsApplication

ROOT=Path(__file__).resolve().parents[1]
RUN='finals_f86eaedbb7c64f12afef1558b6f6b7e1'
rows=FinalsStateStore(ROOT/'.tmp/finals_v2/runs')._journal(RUN)
assert rows and rows[-1]['state'].get('execution')
blocked={'runtime_provenance','model_request_provenance','session_capability','failure_history'}
def clean(value):
    if isinstance(value,dict):
        return {k:('演示计划员' if k in {'actor','approved_by'} else clean(v)) for k,v in value.items()
                if k not in blocked and not re.search(r'password|secret|credential|api_key|authorization_header',k,re.I)}
    if isinstance(value,list): return [clean(v) for v in value]
    if isinstance(value,str):
        value=value.replace('青爷','演示计划员')
        value=re.sub(r'/Users/[^\s"\']+', '[本地路径已隐藏]',value)
        return value
    return value
boot=clean(FinalsApplication().bootstrap())
boot.update(session_capability='',live_enabled=False,external_enabled=True)
spec=[(1,'发现证据缺口','investigate'),(2,'继续向人求证','evidence'),(3,'三种恢复方案','decision'),
      (4,'方案已批准','execution'),(5,'MES变化：审批失效','execution'),(6,'重新测算','decision'),(8,'交付与回读','execution')]
snapshots=[]
for revision,label,stage in spec:
    state=next(r['state'] for r in reversed(rows) if r['state']['revision']==revision)
    snapshots.append({'label':label,'stage':stage,'run':clean(state),'source_hash':next(r['state_hash'] for r in reversed(rows) if r['state']['revision']==revision)})
data={'boot':boot,'snapshots':snapshots,'source_run':RUN,'source_journal_head':rows[-1]['entry_hash'],'recorded':True}
dest=ROOT/'frontend/site/showcase/recording.json'
dest.write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps({'snapshots':len(snapshots),'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}))
