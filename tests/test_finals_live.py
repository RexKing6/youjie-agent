import json
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import BaseModel, ValidationError

from delivery_guard.finals_live import BudgetLedger, BudgetStop, FinalsLiveModel, MAX_CALLS, RESERVE_MICROYUAN


def test_request_limit_survives_new_instances(tmp_path):
    path = tmp_path / "budget.jsonl"
    for _ in range(MAX_CALLS):
        ledger = BudgetLedger(path)
        request_id = ledger.reserve()
        ledger.settle(request_id, {"prompt_tokens": 1, "completion_tokens": 1}, 1)
    with pytest.raises(BudgetStop):
        BudgetLedger(path).reserve()
    assert BudgetLedger(path).snapshot()["requests"] == 100


def test_uncertain_failures_keep_money_reserved(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    count = 20_000_000 // RESERVE_MICROYUAN
    for _ in range(count):
        ledger.reserve()
    with pytest.raises(BudgetStop):
        ledger.reserve()
    assert ledger.snapshot()["accounted_microyuan"] == count * RESERVE_MICROYUAN
    assert ledger.snapshot()["uncertain_requests"] == count


def test_explicit_uncapped_authorization_preserves_usage_and_integrity(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl", uncapped=True)
    for _ in range(101):
        ledger.reserve()
    assert ledger.snapshot()["requests"] == 101
    assert ledger.snapshot()["accounted_microyuan"] == 101 * RESERVE_MICROYUAN
    with ledger.locked() as (stream, _rows):
        ledger.append(stream, {"kind": "halt", "reason": "test_integrity_guard"})
    with pytest.raises(BudgetStop):
        ledger.reserve()


def test_missing_usage_halts_future_calls(tmp_path):
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    request_id = ledger.reserve()
    with pytest.raises(BudgetStop):
        ledger.settle(request_id, {}, 10)
    with pytest.raises(BudgetStop):
        BudgetLedger(ledger.path).reserve()
    assert ledger.snapshot()["halted"]


def test_shared_ledger_concurrency_and_repeated_settlement(tmp_path):
    path = tmp_path / "budget.jsonl"
    def one(_):
        ledger = BudgetLedger(path)
        request_id = ledger.reserve()
        ledger.settle(request_id, {"prompt_tokens": 100, "completion_tokens": 100}, 1)
        return request_id
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(one, range(20)))
    ledger = BudgetLedger(path)
    assert ledger.snapshot()["requests"] == 20
    assert ledger.snapshot()["accounted_microyuan"] == 20 * 4800
    with pytest.raises(BudgetStop):
        ledger.settle(ids[0], {"prompt_tokens": 0, "completion_tokens": 0}, 1)


@pytest.mark.parametrize("url,key", [
    ("https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "test-only-not-real"),
    ("https://coding.dashscope.aliyuncs.com/v1", "test-only-not-real"),
    ("https://evil.example/v1", "test-only-not-real"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "sk-sp-not-a-real-key")])
def test_configuration_rejected_before_any_network_request(tmp_path, url, key):
    path = tmp_path / "synthetic_config.toml"
    path.write_text(f'DELIVERY_GUARD_LLM_BASE_URL = "{url}"\nDELIVERY_GUARD_LLM_MODEL = "qwen3.8-max"\nDELIVERY_GUARD_API_KEY = "{key}"\n')
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    with pytest.raises(BudgetStop):
        FinalsLiveModel(config_path=path, ledger=ledger)
    assert not ledger.path.exists()


def configured_test_model(tmp_path):
    path = tmp_path / "synthetic_config.toml"
    path.write_text('DELIVERY_GUARD_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"\nDELIVERY_GUARD_LLM_MODEL = "qwen3.8-max"\nDELIVERY_GUARD_API_KEY = "not-real-test-key"\n')
    return FinalsLiveModel(config_path=path, ledger=BudgetLedger(tmp_path / "ledger.jsonl"))


class Reply(BaseModel):
    value: int


def test_operator_plan_opt_in_is_exact_and_does_not_dispatch(tmp_path):
    path = tmp_path / "synthetic_config.toml"
    path.write_text('DELIVERY_GUARD_LLM_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"\nDELIVERY_GUARD_LLM_MODEL = "qwen3.8-max"\nDELIVERY_GUARD_API_KEY = "sk-sp-not-real"\n')
    ledger = BudgetLedger(tmp_path / "budget.jsonl")
    model = FinalsLiveModel(config_path=path, ledger=ledger, operator_token_plan=True)
    assert model.mode == "live"
    assert not ledger.path.exists()
    with pytest.raises(BudgetStop):
        FinalsLiveModel(config_path=path, ledger=ledger)
    path.write_text(path.read_text().replace("token-plan.cn-beijing.maas.aliyuncs.com", "evil.example"))
    with pytest.raises(BudgetStop):
        FinalsLiveModel(config_path=path, ledger=ledger, operator_token_plan=True)


def test_transport_success_and_invalid_schema_are_both_accounted(tmp_path):
    model = configured_test_model(tmp_path)
    class Transport:
        calls = 0
        def open(self, request, timeout):
            self.calls += 1
            body = json.loads(request.data)
            assert body["enable_thinking"] is False
            assert "thinking_budget" not in body
            assert body["stream"] is True
            assert body["max_completion_tokens"] == 4096
            content = '{"value":7}' if self.calls == 1 else '{"value":"invalid"}'
            chunks = [{"choices":[{"delta":{"reasoning_content":"PRIVATE_REASONING"}}]},
                      {"choices":[{"delta":{"content":content},"finish_reason":"stop"}]},
                      {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":20}}]
            return io.BytesIO((''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode())
    model.opener = Transport()
    args = {"replay_key": "test", "system_prompt": "test", "user_text": "synthetic", "schema": Reply}
    assert model.complete_structured(**args).value == 7
    with pytest.raises(ValidationError):
        model.complete_structured(**args)
    assert model.ledger.snapshot()["requests"] == 2
    assert model.ledger.snapshot()["accounted_microyuan"] == 2 * (100 * 12 + 20 * 36)
    assert "not-real-test-key" not in model.ledger.path.read_text()


def test_stream_public_summary_excludes_private_reasoning(tmp_path):
    class Summary(BaseModel):
        reason: str
    model = configured_test_model(tmp_path)
    updates = []
    model.on_public_progress = updates.append
    class Transport:
        def open(self, *args, **kwargs):
            chunks = [{"choices":[{"delta":{"reasoning_content":"PRIVATE_REASONING"}}]},
                {"choices":[{"delta":{"content":'{"reason":"Check '}}]},
                {"choices":[{"delta":{"content":'approval"}'},"finish_reason":"stop"}]},
                {"usage":{"prompt_tokens":50,"completion_tokens":30},"choices":[]}]
            return io.BytesIO((''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode())
    model.opener = Transport()
    result = model.complete_structured(replay_key='test', system_prompt='test', user_text='test', schema=Summary)
    assert result.reason == 'Check approval'
    assert 'Check ' in updates and 'Check approval' in updates
    assert 'PRIVATE_REASONING' not in str(updates) + model.ledger.path.read_text()


def test_transport_error_is_redacted_and_never_retried(tmp_path):
    model = configured_test_model(tmp_path)
    class Transport:
        calls = 0
        def open(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("Bearer not-real-test-key provider text")
    model.opener = Transport()
    with pytest.raises(RuntimeError) as error:
        model.complete_structured(replay_key="test", system_prompt="test", user_text="synthetic", schema=Reply)
    assert "not-real-test-key" not in str(error.value)
    assert model.opener.calls == 1
    assert model.ledger.snapshot()["uncertain_requests"] == 1


@pytest.mark.parametrize('ending', ['', 'data: [DONE]\n\n'])
def test_truncated_stream_never_yields_valid_action(tmp_path, ending):
    model = configured_test_model(tmp_path)
    class Transport:
        def open(self, *args, **kwargs):
            chunk = {'choices':[{'delta':{'content':'{"value":7}'},'finish_reason':'length'}]}
            return io.BytesIO(('data: '+json.dumps(chunk)+'\n\n'+ending).encode())
    model.opener = Transport()
    with pytest.raises(RuntimeError):
        model.complete_structured(replay_key='test', system_prompt='test', user_text='test', schema=Reply)
    assert model.ledger.snapshot()['uncertain_requests'] == 1


def test_provider_quota_is_distinguished_without_leaking_body(tmp_path):
    from urllib.error import HTTPError
    from delivery_guard.finals_live import ModelTransportError
    model=configured_test_model(tmp_path)
    class Quota:
        def open(self,*args,**kwargs):
            raise HTTPError("https://test.invalid",429,"private",{"Retry-After":"360000"},
                io.BytesIO(b'{"error":{"code":"insufficient_quota","message":"private"}}'))
    model.opener=Quota()
    with pytest.raises(ModelTransportError) as error:
        model.complete_structured(replay_key="test",system_prompt="test",user_text="test",schema=Reply)
    assert error.value.error_code=="MODEL_QUOTA_EXHAUSTED"
    assert error.value.retry_after_seconds==360000
    assert "private" not in str(error.value)


def test_oversized_input_never_dispatches(tmp_path):
    model = configured_test_model(tmp_path)
    class Transport:
        def open(self, *args, **kwargs):
            pytest.fail("Request should not have been sent")
    model.opener = Transport()
    with pytest.raises(BudgetStop):
        model.complete_structured(replay_key="test", system_prompt="test", user_text="测" * 24000, schema=Reply)
    assert not model.ledger.path.exists()


def test_http_429_is_not_retried_or_reported_success(tmp_path):
    from urllib.error import HTTPError
    model = configured_test_model(tmp_path)
    class Limited:
        calls = 0
        def open(self, *args, **kwargs):
            self.calls += 1
            raise HTTPError("https://test.invalid", 429, "secret-provider-message", {},
                            io.BytesIO(b"not-real-test-key"))
    model.opener = Limited()
    with pytest.raises(RuntimeError) as error:
        model.complete_structured(replay_key="test", system_prompt="test", user_text="synthetic", schema=Reply)
    assert model.opener.calls == 1
    assert "not-real-test-key" not in str(error.value) and "secret-provider-message" not in str(error.value)
    assert error.value.http_status == 429 and error.value.error_code == "MODEL_RATE_LIMITED"
    assert model.ledger.snapshot()["uncertain_requests"] == 1


@pytest.mark.parametrize("usage", [None, [], {"prompt_tokens": -1, "completion_tokens": 0}, {"prompt_tokens": 1, "completion_tokens": 9000}])
def test_invalid_usage_keeps_reservation_and_halts(tmp_path, usage):
    ledger = BudgetLedger(tmp_path / "ledger.jsonl")
    request_id = ledger.reserve()
    with pytest.raises(BudgetStop):
        ledger.settle(request_id, usage, 1)
    assert ledger.snapshot()["halted"]
    assert ledger.snapshot()["accounted_microyuan"] == RESERVE_MICROYUAN


def test_corrupt_ledger_cannot_reduce_cost_to_get_extra_calls(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.jsonl")
    request_id = ledger.reserve()
    with ledger.path.open("a") as stream:
        stream.write(json.dumps({"kind": "settle", "id": request_id, "estimated_microyuan": -100000000}) + "\n")
    with pytest.raises(BudgetStop):
        ledger.reserve()
