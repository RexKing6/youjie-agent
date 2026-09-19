"""Local source candidate; explicit files, deterministic hashes, no submission."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=('src/**/*.py','tests/*.py','data/**/*.json','data/**/*.md','data/**/*.txt',
    'data/**/*.eml','data/**/*.csv','data/**/*.png','data/**/*.pdf','data/**/*.xlsb',
    'contracts/**/*.json','contracts/**/*.yaml','contracts/**/*.md','scripts/*.py','scripts/*.php',
    'configs/finals_v2*.json','configs/finals_wiki_semantics_v3.json','configs/finals_live_evaluation_v*.json',
    'frontend/site/app/**/*','frontend/site/components/**/*','frontend/site/hooks/**/*',
    'frontend/site/lib/**/*','frontend/site/public/**/*','.github/ISSUE_TEMPLATE/*.md')
EXACT=('README.md','LICENSE','THIRD_PARTY_NOTICES.md','pyproject.toml','requirements.txt',
    'requirements-dev.txt','app.py','AGENTS.md','CONTRIBUTING.md','docs/finals_complete_spec_v2.md',
    'docs/finals_v2_regression_20260918.md','docs/finals_v2_input_repair_20260918.md',
    'docs/finals_v2_regression_20260918_03.md','docs/finals_v2_stop_repair_20260918.md',
    'docs/finals_v2_failure_persistence_acceptance_20260918.md',
    'docs/finals_v2_wiki_semantics_review_20260918.md',
    'docs/finals_v2_acceptance_matrix_20260918.md',
    'docs/finals_v2_reply_context_review_20260918.md',
    'docs/finals_v2_followup_clock_review_20260918.md',
    'docs/finals_v2_current_evidence_20260918.md',
    'docs/finals_v2_readiness_20260918.md',
    'docs/finals_v2_candidate_validation_20260918_05.md',
    'docs/finals_v2_new_expression_review_20260918.md',
    'docs/finals_v2_shared_timeline_20260918.md',
    'docs/finals_v2_browser_pause_20260918.md',
    'docs/finals_v2_browser_failure_zoom_20260918.md',
    'docs/finals_v2_browser_acceptance_20260918.md','docs/finals_v2_dependency_review_20260917.md',
    'artifacts/finals_v2/browser_20260918_01/failed_before_repair.json',
    'artifacts/finals_v2/browser_20260918_01/repaired_browser_chain.json',
    'docs/finals_v2_implementation_readiness_20260917.md','docs/finals_v2_operator_walkthrough.md',
    'docs/finals_v2_reproduction.md','docs/finals_v2_stage_script_20260917.md','docs/finals_demo_and_questions.md',
    'artifacts/public_data_graph_run.json',
    'frontend/site/package.json','frontend/site/package-lock.json','frontend/site/tsconfig.json',
    'frontend/site/vite.config.ts','frontend/site/next.config.ts','frontend/site/next-env.d.ts',
    'frontend/site/components.json','frontend/site/.openai/hosting.json')
REPORTS=('real_chain_20260917_01','real_chain_20260917_02','real_chain_20260917_03',
    'tasks_live_20260917_02','tasks_live_20260917_03','tasks_live_20260917_04',
    'local_checks_20260917_09','local_checks_20260918_01','tasks_live_20260918_01',
    'local_checks_20260918_06','tasks_live_20260918_02','tasks_live_20260918_03',
    'tasks_live_20260918_04','real_chain_20260918_01','failure_http_20260918_02',
    'model_repair_20260917_03',
    'local_checks_20260918_11','tasks_live_20260918_05','tasks_live_20260918_06',
    'tasks_live_20260918_07','real_chain_20260918_03','failure_http_20260918_03',
    'document_injection_20260918_02','order_total_live_20260918_02',
    'tasks_live_20260918_09','tasks_live_20260918_10','tasks_live_20260918_11',
    'independent_live_20260918_01','release_holdout_20260918_01','release_holdout_20260918_02',
    'release_expression_regression_20260918_02','release_expression_regression_20260918_03',
    'new_expression_regression_20260918_01','new_expression_regression_20260918_02',
    'numeric_diagnosis_20260918_01','attachment_diagnosis_20260918_01',
    'document_injection_20260918_04','document_injection_20260918_05',
    'local_checks_20260918_17','real_chain_20260918_06','failure_http_20260918_05',
    'legacy_regression_20260918_02',
    'erp_provision_20260917','erp_provision_20260917_02')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists(): p.error('Preserve existing candidate')
    selected={ROOT/name for name in EXACT}
    for pattern in PATTERNS: selected.update(f for f in ROOT.glob(pattern) if f.is_file())
    selected.update(ROOT/'artifacts/finals_v2'/name/'report.json' for name in REPORTS)
    missing=[str(f.relative_to(ROOT)) for f in selected if not f.is_file()]
    if missing: raise ValueError(f'Missing required files: {missing}')
    manifest={'schema':'finals_local_source_candidate/v1','submission_ready':False,
              'published':False,'files':{},'limits':['No final deck/video','No credential/runtime DB',
              'Fresh dependency installation and browser acceptance remain separate checks']}
    for f in sorted(selected):
        rel=f.relative_to(ROOT).as_posix()
        if f.is_symlink() or any(part in ('.tmp','.git','.streamlit','node_modules','__pycache__') for part in f.relative_to(ROOT).parts):
            raise ValueError('Disallowed source path')
        if f.name.startswith('.env') or f.suffix in ('.sqlite3','.db','.pem','.key'):
            raise ValueError('Disallowed runtime or credential file')
        manifest['files'][rel]={'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    def add(z,name,data):
        info=ZipInfo('goai_delivery_guard/'+name,(2026,9,17,0,0,0));info.compress_type=ZIP_DEFLATED
        info.external_attr=0o100644<<16;z.writestr(info,data)
    with ZipFile(a.output,'x',compression=ZIP_DEFLATED) as z:
        for rel in manifest['files']: add(z,rel,(ROOT/rel).read_bytes())
        add(z,'CANDIDATE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode())
    with ZipFile(a.output) as z:
        assert z.testzip() is None
        for rel,proof in manifest['files'].items():
            assert hashlib.sha256(z.read('goai_delivery_guard/'+rel)).hexdigest()==proof['sha256']
    print(json.dumps({'path':str(a.output.resolve()),'files':len(selected),'bytes':a.output.stat().st_size,
        'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),'submission_ready':False}))

if __name__=='__main__':main()
