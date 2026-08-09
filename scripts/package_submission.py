"""Create a deterministic, source-only competition handoff archive."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "delivery_guard_submission.zip"
FIXED_TIMESTAMP = (2026, 8, 9, 0, 0, 0)

ROOT_FILES = ("AGENTS.md", "README.md", "LICENSE", "pyproject.toml", "app.py")
PATTERNS = (
    "src/delivery_guard/*.py",
    "data/**/*.json",
    "data/**/*.md",
    "data/**/*.txt",
    "data/**/*.xlsb",
    "tests/*.py",
    "scripts/*.py",
    "docs/*.md",
    "docs/youjie_goai_pitch.pptx",
    "docs/youjie_demo.mp4",
    "artifacts/demo_run.json",
    "artifacts/adversarial_report.json",
    "artifacts/demo_screenshot.jpg",
    "artifacts/agent_demo_run.json",
    "artifacts/agent_eval_report.json",
    "artifacts/agent_eval_report.md",
    "artifacts/infeasible_diagnostic.json",
    "artifacts/public_data_graph_run.json",
    "artifacts/chaos_drill_run.json",
)


def selected_files() -> list[Path]:
    paths = [ROOT / name for name in ROOT_FILES]
    for pattern in PATTERNS:
        paths.extend(ROOT.glob(pattern))
    return sorted({path for path in paths if path.is_file() and path != OUTPUT})


def main() -> None:
    files = selected_files()
    if not files:
        raise SystemExit("no files selected for submission")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(ROOT)
            info = ZipInfo(f"goai_delivery_guard/{relative.as_posix()}", FIXED_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    print(f"packaged {len(files)} files -> {OUTPUT}")


if __name__ == "__main__":
    main()
