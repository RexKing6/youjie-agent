"""Create a deterministic, source-only competition handoff archive."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "frontend" / "site"
OUTPUT = ROOT / "artifacts" / "youjie_semifinal_submission.zip"
FIXED_TIMESTAMP = (2026, 8, 26, 0, 0, 0)

ROOT_FILES = (
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml",
    "requirements.txt", "requirements-dev.txt", "app.py",
)
PATTERNS = (
    "src/delivery_guard/**/*.py",
    "contracts/**/*.yaml",
    "contracts/**/*.json",
    "contracts/**/*.md",
    "data/**/*.json",
    "data/**/*.md",
    "data/**/*.txt",
    "data/**/*.eml",
    "data/**/*.csv",
    "data/**/*.png",
    "data/**/*.pdf",
    "data/**/*.xlsb",
    "tests/*.py",
    "scripts/*.py",
    "scripts/*.mjs",
    "docs/*.md",
    "docs/youjie_goai_semifinal_pitch_8slides.pptx",
    "docs/youjie_goai_semifinal_pitch_8slides.pdf",
    "docs/youjie_semifinal_demo.mp4",
    "docs/youjie_semifinal_demo.zh-CN.srt",
    "artifacts/demo_run.json",
    "artifacts/adversarial_report.json",
    "artifacts/demo_screenshot.jpg",
    "artifacts/agent_demo_run.json",
    "artifacts/agent_eval_report.json",
    "artifacts/agent_eval_report.md",
    "artifacts/infeasible_diagnostic.json",
    "artifacts/public_data_graph_run.json",
    "artifacts/chaos_drill_run.json",
    "artifacts/semifinal_comparison_report.json",
    "artifacts/semifinal_comparison_report.md",
    "artifacts/live_agent_eval_report.json",
    "artifacts/live_agent_eval_report.md",
    "artifacts/live_semifinal_report.json",
    "artifacts/integration_validation_report.json",
    "artifacts/erpnext_real_validation.json",
    "artifacts/openmes_real_validation.json",
)

SITE_PATTERNS = (
    "app/**/*",
    "components/**/*",
    "hooks/**/*",
    "lib/**/*",
    "public/**/*",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.ts",
    "next.config.ts",
    "next-env.d.ts",
    "components.json",
    ".openai/**/*",
    ".oxlintrc.json",
    ".oxfmtrc.json",
)

EXCLUDED_FILES = {
    "docs/ppt_feedback_update_plan.md",
}


def selected_files() -> list[tuple[Path, str]]:
    paths = [ROOT / name for name in ROOT_FILES]
    for pattern in PATTERNS:
        paths.extend(ROOT.glob(pattern))
    selected = {
        (path, f"goai_delivery_guard/{path.relative_to(ROOT).as_posix()}")
        for path in paths
        if path.is_file()
        and path != OUTPUT
        and path.relative_to(ROOT).as_posix() not in EXCLUDED_FILES
    }
    for pattern in SITE_PATTERNS:
        for path in SITE_ROOT.glob(pattern):
            if path.is_file():
                selected.add(
                    (
                        path,
                        f"goai_delivery_guard/frontend/site/{path.relative_to(SITE_ROOT).as_posix()}",
                    )
                )
    return sorted(selected, key=lambda item: item[1])


def main() -> None:
    files = selected_files()
    if not files:
        raise SystemExit("no files selected for submission")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path, archive_name in files:
            info = ZipInfo(archive_name, FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(f"packaged {len(files)} files -> {OUTPUT}")


if __name__ == "__main__":
    main()
