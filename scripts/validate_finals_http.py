"""Explicit local live integration; no ERP/MES writes, preserves every state."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        parser.error('Report exists')
    files = sorted((ROOT / 'src/delivery_guard').glob('finals_*.py'))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report = {'mode': 'live', 'transport': 'loopback HTTP', 'states': [], 'complete': False, 'frozen_sha256': hashes}
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as f:
        json.dump(report, f)
    def post(path, data):
        req = urllib.request.Request('http://127.0.0.1:8766' + path, data=json.dumps(data).encode(),
            headers={'Content-Type': 'application/json', 'Origin': 'http://localhost:3000'})
        with urllib.request.urlopen(req, timeout=240) as response:
            state = json.load(response)
        report['states'].append({'operation': path, 'state': state})
        save()
        assert state['mode'] == 'live'
        print(path, state['status'], flush=True)
        return state
    try:
        s = post('/start', {'text': '订单O-208的A1延期24小时，A2以前用过，调查能否替代', 'case_id': 'two_reply', 'policy': 'adaptive', 'mode': 'live'})
        assert s['status'] == 'awaiting_evidence'
        for text, documents, status in [('王工说技术上应该没问题', [], 'awaiting_evidence'),
                                        ('附当前订单客户批准邮件，请核验范围和批次', ['AP-CURRENT'], 'awaiting_approval')]:
            s = post('/reply', {'run_id': s['run_id'], 'revision': s['revision'], 'text': text, 'document_ids': documents})
            assert s['status'] == status
        assert s['reply_count'] == 2 and not s['drafts'] and s['approval'] is None
        assert len([t for t in s['trace'] if t['node'] == 'targeted_followup']) == 1
        s = post('/wiki', {'run_id': s['run_id'], 'revision': s['revision']})
        assert s['wiki']['mode'] == 'live'
        by_id = {d['id']: d for d in s['wiki']['documents']}
        for claim in s['wiki']['claims']:
            c = claim['summary_citation']
            assert by_id[c['document_id']]['body'][c['start']:c['end']] == c['quote'] == claim['model_selected_excerpt']
            assert claim['source_role_label'] in claim['summary']
        s = post('/approve', {'run_id': s['run_id'], 'revision': s['revision'], 'plan_id': s['plans'][0]['plan']['plan_id'], 'actor': '本地验证员'})
        assert s['drafts']
        s = post('/feedback', {'run_id': s['run_id'], 'revision': s['revision'], 'hold': 200})
        assert s['status'] == 'awaiting_approval' and not s['drafts'] and s['approval'] is None
        assert s['qualification']['eligible_a2'] == 300 and not s['history'][-1]['approval']['valid']
        report['unchanged'] = hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        assert report['unchanged']
        report.update(complete=True, passed=True)
    except Exception as exc:
        report.update(passed=False, error_type=type(exc).__name__)
    save()
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
