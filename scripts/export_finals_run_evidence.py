"""Read-only loopback evidence export; never print or persist the session capability."""
import argparse
import json
from pathlib import Path
import re
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'finals_[a-f0-9]{32}', args.run_id):
        parser.error('Invalid run ID')
    if args.output.exists():
        parser.error('Preserve existing evidence')
    base = 'http://127.0.0.1:8766'
    with urllib.request.urlopen(base + '/bootstrap', timeout=30) as response:
        capability = json.load(response)['session_capability']
    request = urllib.request.Request(base + '/runs/' + args.run_id + '/evidence',
                                     headers={'X-Youjie-Session': capability})
    with urllib.request.urlopen(request, timeout=30) as response:
        evidence = json.load(response)
    if evidence['state']['run_id'] != args.run_id or not evidence['journal']['chain_valid']:
        raise ValueError('Evidence identity or journal mismatch')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'run_id': args.run_id, 'status': evidence['state']['status'],
                      'runtime_compatible': evidence['runtime_compatible'], 'read_only': True}))


if __name__ == '__main__':
    main()
