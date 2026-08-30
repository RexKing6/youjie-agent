"""Build a font-safe PDF from the visually verified semifinal slide renders."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
SLIDES = ROOT / "artifacts/pitch_erpnext_update/final-preview"
OUTPUT = ROOT / "docs/youjie_goai_semifinal_pitch.pdf"
PAGE = (960, 540)


def main() -> None:
    images = sorted(SLIDES.glob("final-slide-*.png"))
    if len(images) != 14:
        raise SystemExit(f"expected 14 rendered slides, found {len(images)}")
    pdf = canvas.Canvas(str(OUTPUT), pagesize=PAGE, pageCompression=1)
    pdf.setTitle("有界 - GOAI 复赛方案")
    pdf.setAuthor("有界项目组")
    for image_path in images:
        pdf.drawImage(
            ImageReader(str(image_path)),
            0,
            0,
            width=PAGE[0],
            height=PAGE[1],
            preserveAspectRatio=True,
            anchor="c",
        )
        pdf.showPage()
    pdf.save()
    print(f"built {len(images)} pages -> {OUTPUT}")


if __name__ == "__main__":
    main()
