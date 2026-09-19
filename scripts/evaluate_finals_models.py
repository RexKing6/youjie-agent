"""Explicit live switch; shared approved ledger, no live-to-offline fallback."""
import argparse
from pathlib import Path

from delivery_guard.finals_evaluation import ROOT, PROTOCOL, evaluate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--operator-token-plan", action="store_true", help="Explicit user-authorized operator evaluation with existing project Token Plan endpoint")
    parser.add_argument("--output", required=True)
    parser.add_argument("--protocol", default=str(PROTOCOL), help="Frozen evaluation protocol; development and held-out protocols must remain separate")
    args = parser.parse_args()
    if args.operator_token_plan and not args.live:
        parser.error("--operator-token-plan requires --live; refusing to silently run offline")
    protocol = Path(args.protocol)
    if not protocol.is_absolute():
        protocol = ROOT / protocol
    if not protocol.is_file():
        parser.error("评测协议不存在；未发起模型请求")
    output = ROOT / args.output
    if output.exists():
        parser.error("输出已存在；请保留旧报告并使用新路径")
    model = None
    if args.live:
        from delivery_guard.finals_live import FinalsLiveModel
        try:
            model = FinalsLiveModel(operator_token_plan=args.operator_token_plan)
        except RuntimeError as exc:
            parser.exit(2, str(exc) + "\n")
    report = evaluate(output, model=model, protocol_path=protocol)
    print(f"mode={report['mode']} complete={report['complete']} automatic_checks_passed={report.get('automatic_checks_passed', False)} report={output}")
    raise SystemExit(0 if report.get("automatic_checks_passed") else 1)


if __name__ == "__main__":
    main()
