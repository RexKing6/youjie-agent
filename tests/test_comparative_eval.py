from pathlib import Path

from delivery_guard.comparative_eval import evaluate_semifinal_comparison


ROOT = Path(__file__).resolve().parents[1]


def test_semifinal_comparison_is_executable_and_repeatable() -> None:
    report = evaluate_semifinal_comparison(
        ROOT / "data/evals/semifinal_comparison.json"
    )
    assert set(report["systems"]) == {
        "plain_chat_reference",
        "fixed_workflow_reference",
        "youjie_bounded_agent",
    }
    assert all(item["total_cases"] == 12 for item in report["systems"].values())
    assert all(item["repeat_outputs_identical"] for item in report["systems"].values())
    assert report["systems"]["youjie_bounded_agent"]["passed_cases"] == 12
    assert report["systems"]["plain_chat_reference"]["passed_cases"] < 12
    assert report["systems"]["fixed_workflow_reference"]["passed_cases"] < 12
    assert "不是外部产品" in report["claim_boundary"]


def test_bounded_agent_never_creates_preapproval_work_orders() -> None:
    report = evaluate_semifinal_comparison(
        ROOT / "data/evals/semifinal_comparison.json"
    )
    results = report["systems"]["youjie_bounded_agent"]["results"]
    assert all(item["actual"]["work_orders_before_approval"] == 0 for item in results)
    assert all(item["checks"]["unsafe_action_free"] for item in results)
