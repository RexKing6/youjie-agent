"""Repeated consumed attachment task; no retry, external writes or raw error text."""
import argparse
import hashlib
import json
from pathlib import Path
from delivery_guard.finals_agent import FinalsInvestigation
from delivery_guard.finals_live import FinalsLiveModel

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists(): parser.error('Preserve prior evidence')
    protocol = ROOT / 'configs/finals_v2_independent_round_v1.json'
    paths = [protocol, Path(__file__), *sorted((ROOT / 'src/delivery_guard').rglob('*.py'))]
    hashes = lambda: {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    case = next(c for c in json.loads(protocol.read_text())['cases'] if c['id'] == 'new_wrong_attachment_twice')
    report = {'complete': False, 'hashes': hashes(), 'rows': [],
              'scope': 'Consumed-input diagnosis, six tasks, fixed/adaptive three repeats each; no retry or external writes.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save(): args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()
    for policy in ('fixed', 'adaptive'):
        for repeat in range(3):
            engine = FinalsInvestigation(model=FinalsLiveModel(operator_token_plan=True))
            state = engine.start(case['text'], case_id=case['case_id'], policy=policy)
            states = [state]
            for reply in case['replies']:
                if state['status'] not in ('needs_input', 'awaiting_evidence'): break
                state = engine.reply(state['run_id'], text=reply['text'],
                                     document_ids=reply.get('documents', []), revision=state['revision'])
                states.append(state)
            report['rows'].append({'policy': policy, 'repeat': repeat, 'states': states})
            save()
            print(policy, repeat, state['status'], flush=True)
    report.update(complete=True, unchanged=report['hashes'] == hashes())
    save()


if __name__ == '__main__': main()
