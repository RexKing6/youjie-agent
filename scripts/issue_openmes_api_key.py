"""Issue one scoped local OpenMES key and write it to an ignored chmod-600 file.

This script intentionally refuses to overwrite an existing file or issue a
second key with the same name. Run it only after explicit credential-write
approval.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from bootstrap_openmes_test import login
from delivery_guard.integration.openmes import OPENMES_UPSTREAM_COMMIT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", default="youjie-local-test-adapter")
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise RuntimeError("refusing to overwrite existing OpenMES credential file")

    api = login(args.base_url)
    existing = api.request("GET", "/api/v1/api-keys").get("data", [])
    if any(row.get("name") == args.name for row in existing):
        raise RuntimeError("an OpenMES API key with this name already exists; not issuing another")
    issued = api.request("POST", "/api/v1/api-keys", {
        "name": args.name,
        "scopes": [
            "erp:orders:import",
            "erp:production:read",
            "erp:quality:read"
        ],
        "is_active": True,
    })
    plaintext = issued.get("plaintext_key")
    if not isinstance(plaintext, str) or not plaintext:
        raise RuntimeError("OpenMES did not return the one-time plaintext API key")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = {
        "base_url": args.base_url,
        "api_key": plaintext,
        "environment": "test",
        "timeout_seconds": "8",
        "upstream_commit": OPENMES_UPSTREAM_COMMIT,
    }
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(descriptor, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({
        "status": "created",
        "credential_file": str(output),
        "key_prefix": issued.get("data", {}).get("key_prefix"),
        "plaintext_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
