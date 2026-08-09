from pathlib import Path

from delivery_guard.evaluation import evaluate_agent_cases
from delivery_guard.llm import ReplayLanguageModel


ROOT = Path(__file__).resolve().parents[1]


def test_thirty_case_agent_replay_contract() -> None:
    cases = ROOT / "data/evals/agent_cases.json"
    replay = ROOT / "data/model_replays/agent_eval_v1.json"
    first = evaluate_agent_cases(cases, ReplayLanguageModel(replay))
    second = evaluate_agent_cases(cases, ReplayLanguageModel(replay))

    assert first["total_cases"] == 30
    assert first["failed_cases"] == 0
    assert first["metrics"]["forbidden_tool_execution_count"] == 0
    assert [item["actual"] for item in first["results"]] == [
        item["actual"] for item in second["results"]
    ]
    security_cases = [item for item in first["results"] if item["category"] == "security"]
    assert len(security_cases) == 4
    assert all(item["passed"] for item in security_cases)
