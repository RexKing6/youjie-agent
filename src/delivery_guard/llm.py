"""Language-model boundary: deterministic replay plus optional live OpenAI-compatible calls."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class LanguageModel(Protocol):
    mode: str
    model_name: str

    def complete_structured(
        self,
        *,
        replay_key: str,
        system_prompt: str,
        user_text: str,
        schema: type[T],
    ) -> T: ...


class ReplayLanguageModel:
    mode = "replay"

    def __init__(self, path: str | Path) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.model_name = payload["model_name"]
        self._responses: dict[str, Any] = payload["responses"]

    def complete_structured(
        self,
        *,
        replay_key: str,
        system_prompt: str,
        user_text: str,
        schema: type[T],
    ) -> T:
        del system_prompt, user_text
        if replay_key not in self._responses:
            raise KeyError(f"missing replay response: {replay_key}")
        return schema.model_validate(self._responses[replay_key])


class OpenAICompatibleLanguageModel:
    mode = "live"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        api_key_env: str = "DELIVERY_GUARD_API_KEY",
        timeout_seconds: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def complete_structured(
        self,
        *,
        replay_key: str,
        system_prompt: str,
        user_text: str,
        schema: type[T],
    ) -> T:
        del replay_key
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing runtime credential in {self.api_key_env}")
        body = {
            "model": self.model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            },
        }
        # Qwen reasoning models default to a slow thinking mode. Incident
        # extraction is a bounded JSON-schema task, so disable thinking to
        # reduce latency and keep structured output reliable.
        if self.model_name.casefold().startswith("qwen"):
            body["enable_thinking"] = False
            body["max_completion_tokens"] = 4096
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"live model request failed: {exc}") from exc
        content = payload["choices"][0]["message"]["content"]
        return schema.model_validate_json(content)
