#!/usr/bin/env python3
"""Fail closed when the public demo requires authentication or cannot be reached."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


AUTH_MARKERS = (
    "share.streamlit.io/-/auth/",
    "/-/login",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class ProbeResult:
    checked_at_utc: str
    url: str
    status: int | None
    location: str | None
    passed: bool
    reason: str


def probe(url: str, timeout: float = 20.0) -> ProbeResult:
    checked_at = datetime.now(timezone.utc).isoformat()
    request = Request(url, headers={"User-Agent": "youjie-semifinal-acceptance/1.0"})
    opener = build_opener(NoRedirect)
    status: int | None = None
    location: str | None = None
    body = ""
    try:
        response = opener.open(request, timeout=timeout)
        status = response.status
        location = response.headers.get("Location")
        body = response.read(64_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        status = exc.code
        location = exc.headers.get("Location")
        body = exc.read(64_000).decode("utf-8", errors="replace")
    except URLError as exc:
        return ProbeResult(checked_at, url, None, None, False, f"network_error: {exc.reason}")

    combined = " ".join(part for part in (location or "", body) if part).lower()
    if any(marker in combined for marker in AUTH_MARKERS):
        return ProbeResult(checked_at, url, status, location, False, "authentication_redirect")
    if status != 200:
        return ProbeResult(checked_at, url, status, location, False, f"unexpected_http_status_{status}")
    return ProbeResult(checked_at, url, status, location, True, "anonymous_http_reachable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="https://youjie-goai-2026.streamlit.app/")
    parser.add_argument("--output", help="Optional JSON evidence path")
    args = parser.parse_args()

    result = probe(args.url)
    payload = json.dumps(asdict(result), ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
