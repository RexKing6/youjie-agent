import hashlib
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

spec = importlib.util.spec_from_file_location("candidate_scan", Path(__file__).resolve().parents[1] / "scripts/scan_finals_candidate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_archive(path, name="README.md", content=b"synthetic", wrong_hash=False):
    manifest = {"files": {name: {"bytes": len(content), "sha256": "wrong" if wrong_hash else hashlib.sha256(content).hexdigest()}}}
    with ZipFile(path, "w") as archive:
        archive.writestr("goai_delivery_guard/" + name, content)
        archive.writestr("goai_delivery_guard/CANDIDATE_MANIFEST.json", json.dumps(manifest))


def test_clean_and_known_secret_are_separate(tmp_path):
    path = tmp_path / "candidate.zip"
    make_archive(path)
    assert module.scan(path)["passed"]
    result = module.scan(path, {b"synthetic"})
    assert not result["passed"]
    assert result["issues"] == ["known_credential_present"]
    assert "synthetic" not in json.dumps(result)


def test_hash_and_credential_path_rejected(tmp_path):
    path = tmp_path / "candidate.zip"
    make_archive(path, ".env", wrong_hash=True)
    result = module.scan(path)
    assert "content_hash_mismatch" in result["issues"]
    assert "credential_or_runtime_file" in result["issues"]


def test_nested_secret_values_not_nonsecret_text():
    assert module.credential_values({"model": "not-sensitive", "nested": [{"api_key": "fake-test-key"}]}) == {b"fake-test-key"}
