"""Verify candidate hashes and known local credential absence without printing secrets."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tomllib
from zipfile import ZipFile


def credential_values(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            sensitive = re.search(r"key|secret|token|password|authorization", str(key), re.I)
            if sensitive and isinstance(child, str) and len(child) >= 8:
                found.add(child.encode())
            found.update(credential_values(child))
    elif isinstance(value, list):
        for child in value:
            found.update(credential_values(child))
    return found


def scan(path, known_values=()):
    issues = []
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            issues.append("duplicate_archive_names")
        manifest_name = "goai_delivery_guard/CANDIDATE_MANIFEST.json"
        manifest = json.loads(archive.read(manifest_name))
        expected = {"goai_delivery_guard/" + name for name in manifest["files"]}
        if set(names) != expected | {manifest_name}:
            issues.append("manifest_coverage")
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or p.parts[0] != "goai_delivery_guard":
                issues.append("unsafe_path")
            if any(part in (".tmp", ".streamlit", ".git", "node_modules", "__pycache__") for part in p.parts):
                issues.append("runtime_directory")
            if p.name.startswith(".env") or p.name in ("secrets.toml", "erpnext_credentials.json", "openmes_credentials.json") or p.suffix in (".db", ".sqlite3", ".pem", ".key"):
                issues.append("credential_or_runtime_file")
            data = archive.read(name)
            if any(value in data for value in known_values):
                issues.append("known_credential_present")
            if re.search(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", data):
                issues.append("private_key_marker")
            if name != manifest_name:
                proof = manifest["files"].get(name.removeprefix("goai_delivery_guard/"))
                if not proof or proof["sha256"] != hashlib.sha256(data).hexdigest() or proof["bytes"] != len(data):
                    issues.append("content_hash_mismatch")
    return {"passed": not issues, "issues": sorted(set(issues)), "members": len(names),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "known_values_checked": len(known_values),
            "scope": "Exact known credential bytes, restricted paths, private-key markers and manifest; not a universal secret detector."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--credential-file", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve existing scan")
    secrets = set()
    for source in args.credential_file:
        raw = source.read_bytes()
        data = tomllib.loads(raw.decode()) if source.suffix == ".toml" else json.loads(raw)
        secrets.update(credential_values(data))
    result = scan(args.archive, secrets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
