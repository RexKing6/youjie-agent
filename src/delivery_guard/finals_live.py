"""Authorized finals-only model transport; no secret logging or credential mutation."""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import tomllib
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SECRET_PATH = ROOT / ".streamlit/secrets.toml"
LEDGER = ROOT / "artifacts/finals_20260916/live_budget_approved_20260916.jsonl"
MAX_CALLS = 100
MAX_MICROYUAN = 20_000_000
# Official Beijing public price checked 2026-09-16, no cache discount assumed.
# https://help.aliyun.com/zh/model-studio/qwen3-8-max
INPUT_MICROYUAN = 12
OUTPUT_MICROYUAN = 36
MAX_BODY_BYTES = 24000
FRAMING_TOKEN_MARGIN = 4096
MAX_OUTPUT = 4096
RESERVE_MICROYUAN = (MAX_BODY_BYTES + FRAMING_TOKEN_MARGIN) * INPUT_MICROYUAN + MAX_OUTPUT * OUTPUT_MICROYUAN


class BudgetStop(RuntimeError):
    pass


class ModelTransportError(RuntimeError):
    """Safe provider status only; never retain body, URL, headers or credentials."""
    def __init__(self, status=None, *, quota_exhausted=False, retry_after_seconds=None):
        self.http_status=status if type(status) is int and 100<=status<=599 else None
        self.retry_after_seconds=retry_after_seconds
        self.error_code="MODEL_QUOTA_EXHAUSTED" if quota_exhausted else "MODEL_RATE_LIMITED" if self.http_status==429 else "MODEL_UNAVAILABLE"
        super().__init__(self.error_code)


class BudgetLedger:
    def __init__(self, path: Path = LEDGER, *, uncapped=False):
        self.path = path
        self.uncapped = uncapped

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.seek(0)
                rows = [json.loads(line) for line in stream if line.strip()]
                yield stream, rows
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def summary(rows):
        reservations, settlements = {}, {}
        for row in rows:
            if not isinstance(row, dict) or row.get("kind") not in {"reserve", "settle", "halt"}:
                raise BudgetStop("预算账本记录无效，已停止")
            if row["kind"] == "reserve":
                if row["id"] in reservations or type(row.get("reserved_microyuan")) is not int or row["reserved_microyuan"] != RESERVE_MICROYUAN:
                    raise BudgetStop("预算账本重复请求ID，已停止")
                reservations[row["id"]] = row["reserved_microyuan"]
            elif row["kind"] == "settle":
                if row["id"] not in reservations or row["id"] in settlements:
                    raise BudgetStop("预算账本结算不一致，已停止")
                if type(row.get("estimated_microyuan")) is not int or not 0 <= row["estimated_microyuan"] <= reservations[row["id"]]:
                    raise BudgetStop("预算账本费用数值无效，已停止")
                settlements[row["id"]] = row["estimated_microyuan"]
        return {"requests": len(reservations),
                "accounted_microyuan": sum(settlements.get(k, v) for k, v in reservations.items()),
                "uncertain_requests": len(reservations) - len(settlements),
                "halted": any(r["kind"] == "halt" for r in rows)}

    @staticmethod
    def append(stream, row):
        stream.seek(0, 2)
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    def snapshot(self):
        with self.locked() as (_stream, rows):
            return self.summary(rows)

    def reserve(self):
        with self.locked() as (stream, rows):
            s = self.summary(rows)
            if s["halted"] or (not self.uncapped and (s["requests"] >= MAX_CALLS or s["accounted_microyuan"] + RESERVE_MICROYUAN > MAX_MICROYUAN)):
                raise BudgetStop("本次授权的请求/费用限额不足或账本已暂停，不再调用模型")
            request_id = uuid4().hex
            self.append(stream, {"kind": "reserve", "id": request_id, "reserved_microyuan": RESERVE_MICROYUAN, "time": time.time()})
            return request_id

    def settle(self, request_id, usage, duration_ms):
        usage = usage if isinstance(usage, dict) else {}
        prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
        valid = (type(prompt) is int and type(completion) is int and
                 0 <= prompt <= MAX_BODY_BYTES + FRAMING_TOKEN_MARGIN and 0 <= completion <= MAX_OUTPUT)
        with self.locked() as (stream, rows):
            if not valid:
                self.append(stream, {"kind": "halt", "id": request_id, "reason": "usage_missing_or_exceeds_reserved_bounds"})
                raise BudgetStop("模型用量缺失或超出预留范围，保留费用预留并暂停")
            if not any(r["kind"] == "reserve" and r["id"] == request_id for r in rows) or any(r["kind"] == "settle" and r["id"] == request_id for r in rows):
                raise BudgetStop("请求不存在或已结算")
            self.append(stream, {"kind": "settle", "id": request_id, "prompt_tokens": prompt,
                                "completion_tokens": completion, "estimated_microyuan": prompt * INPUT_MICROYUAN + completion * OUTPUT_MICROYUAN,
                                "duration_ms": duration_ms})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("模型接口重定向被拒绝")


class FinalsLiveModel:
    mode = "live"

    def __init__(self, *, ledger=None, config_path=SECRET_PATH, operator_token_plan=False):
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.model_name = config.get("DELIVERY_GUARD_LLM_MODEL", "")
        self.base_url = config.get("DELIVERY_GUARD_LLM_BASE_URL", "").rstrip("/")
        self._api_key = config.get("DELIVERY_GUARD_API_KEY", "")
        operator_plan = operator_token_plan and self.base_url == "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        if ("token-plan." in self.base_url or "coding." in self.base_url) and not operator_plan:
            raise BudgetStop("当前是Token Plan/Coding Plan地址，官方不允许用于后端；请配置个人按量付费Key及配套地址")
        if (self.base_url != "https://dashscope.aliyuncs.com/compatible-mode/v1" and not operator_plan) or self.model_name != "qwen3.8-max":
            raise BudgetStop("当前限额实现仅核验北京按量付费qwen3.8-max；不自动更换模型或地址")
        if not isinstance(self._api_key, str) or not self._api_key.strip() or (self._api_key.startswith("sk-sp-") and not operator_plan):
            raise BudgetStop("需要本项目已配置的个人按量付费Key，不可复用套餐Key")
        # Explicit subsequent user authorization removes aggregate caps only for
        # this project's operator-initiated Token Plan runs. Keep all accounting.
        self.ledger = ledger or BudgetLedger(uncapped=operator_plan)
        self.opener = urllib.request.build_opener(NoRedirect())

    def complete_structured(self, *, replay_key, system_prompt, user_text, schema):
        del replay_key
        body = {"model": self.model_name, "temperature": 0, "enable_thinking": False,
                "stream": True, "stream_options": {"include_usage": True},
                "max_completion_tokens": MAX_OUTPUT,
                "messages": [{"role": "system", "content": system_prompt + " explanation、reason、context字段只写给用户的简短判断摘要（最多两句话），不输出内部逐步推理。"}, {"role": "user", "content": user_text}],
                "response_format": {"type": "json_schema", "json_schema": {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}}}
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_BODY_BYTES:
            raise BudgetStop("请求超出本次已限定输入长度，未发出模型调用")
        request_id = self.ledger.reserve()
        request = urllib.request.Request(self.base_url + "/chat/completions", data=data,
            headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"}, method="POST")
        started = time.monotonic()
        try:
            with self.opener.open(request, timeout=60) as response:
                content, usage, total, done, finish = "", {}, 0, False, None
                for line in response:
                    total += len(line)
                    if total > 2_000_000:
                        raise ValueError("oversized response")
                    if not line.startswith(b"data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == b"[DONE]":
                        done = True
                        break
                    chunk = json.loads(payload)
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices", []):
                        finish = choice.get("finish_reason") or finish
                        # Never copy, persist or publish the provider's private reasoning field.
                        delta = choice.get("delta", {}).get("content")
                        if isinstance(delta, str):
                            content += delta
                            match = re.search(r'"(?:reason|explanation|context)"\s*:\s*"((?:[^"\\]|\\.)*)', content)
                            if match and getattr(self, "on_public_progress", None):
                                try:
                                    summary = json.loads('"' + match[1] + '"')
                                except ValueError:
                                    continue
                                self.on_public_progress(summary[:600])
                if not done or finish != "stop":
                    raise ValueError("incomplete response")
                result = {"usage": usage, "choices": [{"message": {"content": content}}]}
        except Exception as exc:
            # No retries; uncertain calls retain their full reservation. Never surface response body or headers.
            quota=False
            retry=None
            if isinstance(exc,urllib.error.HTTPError):
                value=exc.headers.get("Retry-After","") if exc.headers else ""
                if value.isdigit() and 0<=int(value)<=2_592_000: retry=int(value)
                try:
                    error=json.loads(exc.read(8192)).get("error",{})
                    quota=isinstance(error,dict) and error.get("code")=="insufficient_quota"
                except Exception: pass
            raise ModelTransportError(exc.code if isinstance(exc,urllib.error.HTTPError) else None,
                                      quota_exhausted=quota,retry_after_seconds=retry) from None
        self.ledger.settle(request_id, result.get("usage", {}), round((time.monotonic() - started) * 1000))
        return schema.model_validate_json(result["choices"][0]["message"]["content"])
