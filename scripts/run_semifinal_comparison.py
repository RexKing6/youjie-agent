"""Generate the reproducible semifinal architecture-comparison artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from delivery_guard.comparative_eval import comparison_markdown, evaluate_semifinal_comparison


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    report = evaluate_semifinal_comparison(ROOT / "data/evals/semifinal_comparison.json")
    json_path = ROOT / "artifacts/semifinal_comparison_report.json"
    md_path = ROOT / "artifacts/semifinal_comparison_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(comparison_markdown(report), encoding="utf-8")
    summary = {
        name: f"{item['passed_cases']}/{item['total_cases']}"
        for name, item in report["systems"].items()
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
