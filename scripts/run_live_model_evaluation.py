"""Run the versioned Agent benchmark against the configured live model.

The API key is read from the ignored Streamlit secrets file and is never
serialized, printed, or included in the report.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delivery_guard.evaluation import evaluate_agent_cases
from delivery_guard.llm import OpenAICompatibleLanguageModel


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATH = ROOT / ".streamlit/secrets.toml"
REQUIRED = (
    "DELIVERY_GUARD_LLM_BASE_URL",
    "DELIVERY_GUARD_LLM_MODEL",
    "DELIVERY_GUARD_API_KEY",
)


def configured_model() -> OpenAICompatibleLanguageModel:
    config = tomllib.loads(SECRET_PATH.read_text(encoding="utf-8"))
    missing = [name for name in REQUIRED if not str(config.get(name, "")).strip()]
    if missing:
        raise SystemExit(f"missing live configuration fields: {', '.join(missing)}")
    for name in REQUIRED:
        os.environ[name] = str(config[name]).strip()
    return OpenAICompatibleLanguageModel(
        base_url=os.environ["DELIVERY_GUARD_LLM_BASE_URL"],
        model_name=os.environ["DELIVERY_GUARD_LLM_MODEL"],
        timeout_seconds=90,
    )


def aggregate_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        result["latency_seconds"]
        for report in reports
        for result in report["results"]
    ]
    case_ids = [item["case_id"] for item in reports[0]["results"]]
    per_case = []
    for case_id in case_ids:
        rows = [
            next(item for item in report["results"] if item["case_id"] == case_id)
            for report in reports
        ]
        per_case.append(
            {
                "case_id": case_id,
                "passes": sum(row["passed"] for row in rows),
                "runs": len(rows),
                "all_passed": all(row["passed"] for row in rows),
                "actual_outputs_identical": all(
                    row["actual"] == rows[0]["actual"] for row in rows[1:]
                ),
                "error_classes": sorted(
                    {row["error_class"] for row in rows if row["error_class"]}
                ),
            }
        )
    metric_names = [
        "intent_accuracy",
        "incident_kind_accuracy",
        "known_entity_resolution_accuracy",
        "missing_field_recall",
        "conflict_detection_recall",
        "correct_next_action_rate",
        "security_flag_recall",
        "case_pass_rate",
        "forbidden_tool_execution_count",
    ]
    aggregate_metrics = {}
    for name in metric_names:
        values = [report["metrics"][name] for report in reports]
        aggregate_metrics[name] = {
            "mean": round(statistics.fmean(values), 4),
            "min": min(values),
            "max": max(values),
        }
    raw_metric_names = list(reports[0]["raw_model_metrics"])
    raw_model_metrics = {}
    for name in raw_metric_names:
        values = [report["raw_model_metrics"][name] for report in reports]
        raw_model_metrics[name] = {
            "mean": round(statistics.fmean(values), 4),
            "min": min(values),
            "max": max(values),
        }
    sorted_latencies = sorted(latencies)
    p95_index = max(0, min(len(sorted_latencies) - 1, int(len(sorted_latencies) * 0.95) - 1))
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_mode": "live",
        "model_name": reports[0]["model_name"],
        "dataset_version": reports[0]["dataset_version"],
        "run_count": len(reports),
        "total_model_calls": len(reports) * reports[0]["total_cases"],
        "claim_boundary": (
            "Live endpoint evaluation on a versioned synthetic benchmark. Results are model-, "
            "prompt-, endpoint-, and time-specific; they do not prove production accuracy."
        ),
        "aggregate_metrics": aggregate_metrics,
        "raw_model_metrics": raw_model_metrics,
        "latency_seconds": {
            "mean": round(statistics.fmean(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "p95": round(sorted_latencies[p95_index], 3),
            "max": round(max(latencies), 3),
        },
        "all_run_pass_counts": [report["passed_cases"] for report in reports],
        "all_run_forbidden_tool_counts": [
            report["metrics"]["forbidden_tool_execution_count"] for report in reports
        ],
        "cases_passing_every_run": sum(item["all_passed"] for item in per_case),
        "cases_with_identical_outputs": sum(
            item["actual_outputs_identical"] for item in per_case
        ),
        "per_case_stability": per_case,
        "runs": reports,
        "secret_handling": {
            "source": ".streamlit/secrets.toml (gitignored)",
            "api_key_in_report": False,
            "endpoint_in_report": False,
        },
    }


def markdown_summary(report: dict[str, Any]) -> str:
    metrics = report["aggregate_metrics"]
    lines = [
        "# Live Agent evaluation",
        "",
        f"- Model: `{report['model_name']}`",
        f"- Dataset: `{report['dataset_version']}`",
        f"- Runs / calls: {report['run_count']} / {report['total_model_calls']}",
        f"- Passed cases per run: {report['all_run_pass_counts']}",
        f"- Forbidden tool calls per run: {report['all_run_forbidden_tool_counts']}",
        f"- Mean / p95 latency: {report['latency_seconds']['mean']}s / {report['latency_seconds']['p95']}s",
        "",
        "## Bounded Agent metrics",
        "",
        "| Metric | Mean | Min | Max |",
        "|---|---:|---:|---:|",
    ]
    for name, values in metrics.items():
        lines.append(f"| {name} | {values['mean']} | {values['min']} | {values['max']} |")
    lines.extend([
        "",
        "## Raw model metrics",
        "",
        "These measure the unguarded structured response before entity resolution and policy routing.",
        "",
        "| Metric | Mean | Min | Max |",
        "|---|---:|---:|---:|",
    ])
    for name, values in report["raw_model_metrics"].items():
        lines.append(f"| {name} | {values['mean']} | {values['min']} | {values['max']} |")
    failed = [item for item in report["per_case_stability"] if not item["all_passed"]]
    lines.extend(["", "## Cases not passing every run", ""])
    if failed:
        lines.extend(
            f"- `{item['case_id']}`: {item['passes']}/{item['runs']}, errors={item['error_classes']}"
            for item in failed
        )
    else:
        lines.append("None.")
    lines.extend(["", report["claim_boundary"], ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/live_agent_eval_report.json"
    )
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be positive")
    model = configured_model()
    reports = [
        evaluate_agent_cases(ROOT / "data/evals/agent_cases.json", model)
        for _ in range(args.runs)
    ]
    aggregate = aggregate_reports(reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = args.output.with_suffix(".md")
    md_path.write_text(markdown_summary(aggregate), encoding="utf-8")
    print(json.dumps({
        "model": aggregate["model_name"],
        "runs": aggregate["run_count"],
        "pass_counts": aggregate["all_run_pass_counts"],
        "forbidden_tool_counts": aggregate["all_run_forbidden_tool_counts"],
        "mean_latency_seconds": aggregate["latency_seconds"]["mean"],
        "output": str(args.output),
        "api_key_logged": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
