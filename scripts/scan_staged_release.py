"""Inspect staged blobs for known local credentials without displaying values."""
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path
from scan_finals_candidate import credential_values

root=Path(__file__).resolve().parents[1]
sources=[root/'.streamlit/secrets.toml',root/'.tmp/openmes_credentials.json',root.parent.parent/'work/goai_erpnext_runtime_20260830/erpnext_credentials.json']
values=set()
for p in sources:
    if p.exists():
        raw=p.read_text();values.update(credential_values(tomllib.loads(raw) if p.suffix=='.toml' else json.loads(raw)))
names=subprocess.check_output(['git','diff','--cached','--name-only','-z'],cwd=root).decode().split('\0')
issues=[];files={}
for name in filter(None,names):
    data=subprocess.check_output(['git','show',f':{name}'],cwd=root)
    if any(v in data for v in values):issues.append({'file':name,'issue':'known_credential'})
    if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|sk-[A-Za-z0-9]{24,}',data):issues.append({'file':name,'issue':'secret_pattern'})
    if any(p in name.split('/') for p in ['.tmp','.streamlit','node_modules']) or Path(name).suffix in ['.mp4','.webm','.sqlite3','.pptx']:issues.append({'file':name,'issue':'excluded_path'})
    files[name]=hashlib.sha256(data).hexdigest()
report={'pass':not issues,'issues':issues,'files':files,'known_values_checked':len(values)}
out=root/'artifacts/finals_release_20260920/checks/staged_scan.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'pass':not issues,'files':len(files),'issues':issues}))
raise SystemExit(bool(issues))
