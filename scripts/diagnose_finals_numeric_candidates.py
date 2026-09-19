"""Observe original structured candidates for two consumed synthetic failures.

No correction, retry, approval, external adapter or credential logging.
"""
import argparse
import hashlib
import json
from pathlib import Path
from delivery_guard.finals_agent import FinalsInvestigation, rule_interpret
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
    report = {'complete': False, 'hashes': hashes(), 'rows': [], 'scope': 'Consumed-input diagnosis, not a new independent evaluation; six tasks, no retry, fixed policy, no external writes.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save(): args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    save()
    cases = json.loads(protocol.read_text())['cases'][:2]
    for case in cases:
        for repeat in range(3):
            provider = FinalsLiveModel(operator_token_plan=True)
            observed = []
            class Observe:
                mode, model_name = provider.mode, provider.model_name
                def complete_structured(self, **kwargs):
                    candidate = provider.complete_structured(**kwargs)
                    if kwargs['schema'].__name__ == 'UserInterpretation':
                        observed.append(candidate.model_dump(mode='json'))
                    return candidate
            engine = FinalsInvestigation(model=Observe())
            state = engine.start(case['text'], case_id=case['case_id'], policy='fixed')
            report['rows'].append({'case_id': case['id'], 'repeat': repeat,
                'input': case['text'], 'deterministic_input': rule_interpret(case['text'], False).model_dump(),
                'model_candidates': observed, 'status': state['status'], 'failure': state.get('failure')})
            save()
            print(case['id'], repeat, state['status'], flush=True)
    report.update(complete=True, unchanged=report['hashes'] == hashes())
    save()


if __name__ == '__main__': main()
