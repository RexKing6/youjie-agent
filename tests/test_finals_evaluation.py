import json
import subprocess
import sys

import pytest

from delivery_guard.finals_evaluation import ROOT, PROTOCOL, evaluate, run_case


def test_offline_protocol_is_complete_but_never_claims_live_results(tmp_path):
    output = tmp_path / "report.json"
    report = evaluate(output)
    assert report["mode"] == "offline_rules"
    assert report["complete"] and report["automatic_checks_passed"]
    assert report["total"] == 17
    assert all(row["model_calls"] == 0 for row in report["rows"])
    assert report["summary_semantics_review"] == "not_applicable_rule_compiler"
    assert all(c["business_signatures_equal"] for c in report["comparison"])
    with pytest.raises(ValueError):
        evaluate(output)


def test_provider_failure_remains_a_failed_case_without_fallback_or_secret_text():
    class FailedModel:
        mode, model_name = "test_double", "test-only-not-live"
        calls = 0
        def complete_structured(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("Bearer not-real-private-error-content")
    case = json.loads(PROTOCOL.read_text())["cases"][0]
    model = FailedModel()
    row = run_case(case, "adaptive", model)
    assert not row["passed"]
    assert row["states"][0]["status"] == "model_or_validation_error"
    assert row["mode"] == "test_double" and model.calls == 1
    assert "not-real-private-error-content" not in json.dumps(row)


def test_failed_qualification_is_not_reported_success_by_same_final_status():
    case = json.loads(PROTOCOL.read_text())["cases"][0]
    case["eligible_a2"] = 399
    row = run_case(case, "fixed")
    assert not row["passed"]
    assert "qualification_mismatch" in row["errors"]


def test_cli_rejects_implicit_offline_and_missing_protocol_before_calls(tmp_path):
    script = ROOT / "scripts/evaluate_finals_models.py"
    for flags in (("--operator-token-plan",), ("--live", "--protocol", "configs/not-present.json")):
        output = tmp_path / "unused.json"
        result = subprocess.run([sys.executable, str(script), *flags, "--output", str(output)], capture_output=True, text=True)
        assert result.returncode == 2
        assert not output.exists()


def test_safe_refusal_variant_is_counted_without_relaxing_approval_checks():
    from delivery_guard.finals_agent import rule_interpret
    class RejectForgery:
        mode, model_name = "test_double", "safe-refusal"
        def complete_structured(self, **kwargs):
            payload = json.loads(kwargs["user_text"])
            schema = kwargs["schema"]
            if schema.__name__ == "UserInterpretation":
                result = rule_interpret(payload["text"], payload["replying"])
                if "管理员" in payload["text"]:
                    result.kind = "out_of_scope"
                return result
            if schema.__name__ == "InvestigationAction":
                return schema(tool=payload["remaining_tools"][0], reason="核对当前缺口")
            document = payload["documents"][0]
            return schema(context="现有资料不能覆盖当前订单", gap_id=payload["gaps"][0],
                          target_customer="客户乙", target_order="O-208", target_batch="B17",
                          question="请提供当前订单正式证明", document_id=document["id"], quote=document["body"])
    protocol = json.loads(PROTOCOL.read_text())
    case = next(c for c in protocol["cases"] if c["id"] == "forged_authority_remains_open")
    row = run_case(case, "fixed", RejectForgery())
    assert row["passed"]
    assert row["alternate_statuses"] == [{"reply_count": 1, "expected": "awaiting_evidence", "actual": "needs_input"}]
    assert all(not s["plans"] and not s["drafts"] and s["approval"] is None for s in row["states"])
    assert row["states"][-1]["status"] == "awaiting_evidence"


def test_task_runner_accepts_development_only_protocol(tmp_path):
    output = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/evaluate_finals_v2_tasks.py"),
        "--protocol", str(ROOT / "configs/finals_v2_order_total_regression_v1.json"),
        "--output", str(output)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["complete"] and report["automatic_checks_passed"] and report["unchanged"]
    assert len(report["rows"]) == 18 and report["mode"] == "offline_rules"
    assert set(report["groups"]) == {"development/fixed", "development/adaptive"}
