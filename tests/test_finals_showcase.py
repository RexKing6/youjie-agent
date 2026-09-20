import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def test_showcase_records_complete_real_demo():
    data=json.loads((ROOT/'frontend/site/showcase/recording.json').read_text())
    states=[s['run'] for s in data['snapshots']]
    assert len(states)==7
    assert states[0]['reply_count']==0 and states[1]['reply_count']==1
    assert len(states[2]['plans'])==3
    assert states[4]['status']=='capacity_changed' and not states[4]['approval']
    assert len(states[5]['plans'])==3
    assert states[-1]['execution']['erp_document']['name']=='MFG-WO-2026-00094'
    assert data['boot']['session_capability']==''
    assert data['boot']['live_enabled'] is False

def test_preview_guard_and_network_policy():
    source=(ROOT/'frontend/site/components/wiki-workbench.tsx').read_text()
    assert 'if(preview)return;' in source
    assert 'if(preview||!busy)return;' in source
    body=source.split('async function act(')[1].split('function showRun')[0]
    assert body.index('if(preview)') < body.index('await work()')
    html=(ROOT/'showcase_static/index.html').read_text()
    assert "connect-src 'none'" in html
    raw=(ROOT/'frontend/site/showcase/recording.json').read_text()
    assert '/Users/' not in raw
    assert not re.search(r'sk-[A-Za-z0-9]{24,}|PRIVATE KEY',raw)
