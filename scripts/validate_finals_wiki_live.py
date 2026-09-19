"""Frozen synthetic Wiki repetition and renamed-source check; explicit live flag."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from delivery_guard.finals_agent import CASES
from delivery_guard.finals_live import FinalsLiveModel
from delivery_guard.finals_wiki import compile_wiki, load_documents

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--protocol', default='configs/finals_wiki_semantics_v1.json')
    args = parser.parse_args()
    output = ROOT / args.output
    if output.exists():
        parser.error('Report exists; preserve first results')
    protocol_path = ROOT / args.protocol
    protocol = json.loads(protocol_path.read_text())
    frozen_paths = [protocol_path, Path(__file__), ROOT / 'data/finals_wiki/sources.json', ROOT / 'src/delivery_guard/finals_wiki.py']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_paths}
    sources = load_documents()
    model = FinalsLiveModel(operator_token_plan=True)
    report = {'mode': 'live', 'complete': False, 'frozen_sha256': hashes, 'rows': [], 'semantic_review': 'pending', 'budget_before': model.ledger.snapshot()}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as f:
        json.dump(report, f)
    for variant in protocol['variants']:
        docs = [deepcopy(sources[i]) for i in CASES[protocol['case']]['docs']]
        for doc in docs:
            for old, new in variant['replacements'].items():
                doc['body'] = doc['body'].replace(old, new)
                doc['title'] = doc['title'].replace(old, new)
        for repeat in range(protocol['repeats']):
            row = {'variant': variant['id'], 'repeat': repeat, 'sources': docs}
            try:
                wiki = compile_wiki(docs, model=model)
                row.update(result=wiki, automatic_pass=bool(wiki['claims']))
            except Exception as exc:
                row.update(automatic_pass=False, error_type=type(exc).__name__)
            report['rows'].append(row)
            report['budget_after'] = model.ledger.snapshot()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(variant['id'], repeat, row['automatic_pass'], flush=True)
    report['complete'] = True
    report['unchanged'] = hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen_paths}
    report['automatic_pass'] = report['unchanged'] and all(r['automatic_pass'] for r in report['rows'])
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['automatic_pass'] else 1)


if __name__ == '__main__':
    main()
