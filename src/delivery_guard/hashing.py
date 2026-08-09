"""Canonical hashing helpers for immutable scenario and approval binding."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_data(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return canonical_data(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, dict):
        return {key: canonical_data(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonical_data(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonical_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def candidate_plan_hash(plan: BaseModel) -> str:
    return stable_hash(plan.model_dump(mode="json", exclude={"evidence"}))
