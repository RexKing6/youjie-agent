"""Record reproducible local checks without replacing previous evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error("Preserve existing evidence")
    paths=sorted((ROOT/"src").rglob("*.py"))+sorted((ROOT/"tests").rglob("*.py"))
    site=ROOT/"frontend/site"
    for directory in ("app", "components", "hooks", "lib"):
        paths.extend(sorted(p for p in (site/directory).rglob("*") if p.is_file()))
    paths.extend(site/name for name in ("package.json", "package-lock.json", "tsconfig.json", "vite.config.ts"))
    hashes=lambda:{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report={"before":hashes(),"checks":[],"scope":"Local code validation, not real ERP/MES execution proof"}
    checks=[("pytest",[sys.executable,"-m","pytest","-q"],ROOT),
            ("compileall",[sys.executable,"-m","compileall","-q","src","app.py","scripts","tests"],ROOT),
            ("typescript",["./node_modules/.bin/tsc","--noEmit"],ROOT/"frontend/site"),
            ("frontend_build",["npm","run","build"],ROOT/"frontend/site"),
            ("dependency_audit",["npm","audit","--json"],ROOT/"frontend/site")]
    for name,cmd,cwd in checks:
        started=time.monotonic()
        result=subprocess.run(cmd,cwd=cwd,text=True,capture_output=True,timeout=180)
        report["checks"].append({"name":name,"command":cmd,"returncode":result.returncode,
            "seconds":round(time.monotonic()-started,3),"stdout":result.stdout,"stderr":result.stderr})
        print(name,result.returncode,flush=True)
    report["unchanged"]=report["before"]==hashes()
    report["passed"]=report["unchanged"] and all(c["returncode"]==0 for c in report["checks"])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__=="__main__": main()
