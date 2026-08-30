"""Hash-bound multi-format evidence records and deterministic conflict detection."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from delivery_guard.context import StrictModel


class EvidenceClaim(StrictModel):
    field_name: str
    value: int | str
    unit: str | None = None
    source_locator: str
    quote: str


class EvidenceRecord(StrictModel):
    evidence_id: str
    filename: str
    media_type: str
    sha256: str
    observed_at: datetime
    freshness_hours: int = Field(gt=0)
    extraction_mode: str
    synthetic_boundary: str
    claims: list[EvidenceClaim]


class EvidenceManifest(StrictModel):
    schema_version: str
    case_as_of: datetime
    provenance: str
    license: str
    derived_fields: list[str]
    seed: int
    records: list[EvidenceRecord]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_evidence_bundle(manifest_path: str | Path) -> dict[str, Any]:
    """Verify source files and expose conflicts without selecting a winner."""

    manifest_file = Path(manifest_path)
    manifest = EvidenceManifest.model_validate_json(
        manifest_file.read_text(encoding="utf-8")
    )
    verified_records: list[dict[str, Any]] = []
    claim_groups: dict[str, list[dict[str, Any]]] = {}
    for record in manifest.records:
        source_path = manifest_file.parent / record.filename
        actual_hash = sha256_file(source_path)
        if actual_hash != record.sha256:
            raise ValueError(
                f"evidence hash mismatch for {record.evidence_id}: "
                f"expected {record.sha256}, got {actual_hash}"
            )
        age_hours = (manifest.case_as_of - record.observed_at).total_seconds() / 3600
        stale = age_hours > record.freshness_hours
        row = {
            **record.model_dump(mode="json"),
            "path": str(source_path),
            "hash_verified": True,
            "age_hours": round(age_hours, 2),
            "stale": stale,
        }
        verified_records.append(row)
        for claim in record.claims:
            claim_groups.setdefault(claim.field_name, []).append(
                {
                    "evidence_id": record.evidence_id,
                    "media_type": record.media_type,
                    "value": claim.value,
                    "unit": claim.unit,
                    "source_locator": claim.source_locator,
                    "quote": claim.quote,
                    "observed_at": record.observed_at.isoformat(),
                    "stale": stale,
                }
            )

    conflicts = []
    for field_name, claims in sorted(claim_groups.items()):
        fresh_values = {json.dumps(item["value"], sort_keys=True) for item in claims if not item["stale"]}
        if len(fresh_values) > 1:
            conflicts.append(
                {
                    "field_name": field_name,
                    "reason": "fresh_sources_disagree",
                    "claims": claims,
                    "requires_human_confirmation": True,
                }
            )
    return {
        "schema_version": manifest.schema_version,
        "case_as_of": manifest.case_as_of.isoformat(),
        "provenance": manifest.provenance,
        "license": manifest.license,
        "records": verified_records,
        "conflicts": conflicts,
        "safe_to_solve": not conflicts,
        "claim_boundary": (
            "Synthetic evidence fixture with hash-bound extraction artifacts; "
            "conflicting fresh values require human confirmation before solving."
        ),
    }
