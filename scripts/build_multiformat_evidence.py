"""Build deterministic synthetic PNG/PDF/CSV evidence and a hash-bound manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data/cases/mendeley_drill/evidence"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_email_png(path: Path) -> None:
    image = Image.new("RGB", (1440, 900), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((90, 55, 1350, 845), radius=24, fill="white", outline="#d8e1ea", width=3)
    draw.rectangle((90, 55, 1350, 135), fill="#0f4c5c")
    draw.text((130, 78), "Synthetic Supplier Mail", font=font(30, bold=True), fill="white")
    draw.text((130, 175), "Q2J seat supply interruption - 48 hour estimate", font=font(38, bold=True), fill="#123244")
    draw.text((130, 245), "From: dispatch@public-seat-supplier.example", font=font(24), fill="#425466")
    draw.text((130, 285), "Issued: 2026-08-25 09:00 CST", font=font(24), fill="#425466")
    draw.line((130, 340, 1310, 340), fill="#d8e1ea", width=2)
    body = [
        "This is a synthetic competition fixture, not a real supplier message.",
        "The public Mendeley seat supplier reports that Q2J shipments",
        "cannot leave the facility for the next 48 hours.",
        "Do not approve or execute any recovery action from this email alone.",
    ]
    y = 395
    for index, line in enumerate(body):
        color = "#d97706" if "48 hours" in line else "#1f3342"
        draw.text((130, y), line, font=font(30, bold="48 hours" in line), fill=color)
        y += 58
    draw.rounded_rectangle((130, 690, 710, 765), radius=16, fill="#fff7e6", outline="#f5c26b", width=2)
    draw.text((160, 710), "UNTRUSTED INPUT - HUMAN CONFIRMATION REQUIRED", font=font(21, bold=True), fill="#8a4b08")
    image.save(path, format="PNG", optimize=True)


def build_carrier_pdf(path: Path) -> None:
    regular = "/System/Library/Fonts/Supplemental/Arial.ttf"
    bold = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
    if Path(regular).exists() and Path(bold).exists():
        pdfmetrics.registerFont(TTFont("EvidenceArial", regular))
        pdfmetrics.registerFont(TTFont("EvidenceArialBold", bold))
        regular_name, bold_name = "EvidenceArial", "EvidenceArialBold"
    else:
        regular_name, bold_name = "Helvetica", "Helvetica-Bold"
    page = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    page.setFillColor(HexColor("#0f4c5c"))
    page.rect(0, height - 96, width, 96, fill=1, stroke=0)
    page.setFillColor(HexColor("#ffffff"))
    page.setFont(bold_name, 20)
    page.drawString(48, height - 58, "SYNTHETIC CARRIER DELIVERY NOTICE")
    page.setFillColor(HexColor("#173646"))
    page.setFont(bold_name, 14)
    page.drawString(48, height - 145, "Notice ID")
    page.setFont(regular_name, 13)
    page.drawString(170, height - 145, "CARRIER-SIM-20260825-017")
    page.setFont(bold_name, 14)
    page.drawString(48, height - 185, "Issued")
    page.setFont(regular_name, 13)
    page.drawString(170, height - 185, "2026-08-25 09:15 CST")
    page.setFont(bold_name, 14)
    page.drawString(48, height - 225, "Material")
    page.setFont(regular_name, 13)
    page.drawString(170, height - 225, "Q2J seat assembly")
    page.setFillColor(HexColor("#fff7e6"))
    page.roundRect(48, height - 360, width - 96, 92, 12, fill=1, stroke=0)
    page.setFillColor(HexColor("#a45208"))
    page.setFont(bold_name, 18)
    page.drawString(72, height - 315, "Current arrival estimate: 72 hours")
    page.setFillColor(HexColor("#173646"))
    page.setFont(regular_name, 13)
    page.drawString(48, height - 410, "Reason: downstream hub congestion after supplier release")
    page.setStrokeColor(HexColor("#d7e0e7"))
    page.line(48, 160, width - 48, 160)
    page.setFillColor(HexColor("#596b78"))
    page.setFont(regular_name, 10)
    page.drawString(48, 130, "Deterministic synthetic GOAI fixture. Not issued by a real carrier.")
    page.drawString(48, 112, "Cannot authorize procurement, scheduling, approval, or equipment control.")
    page.save()


def build_manifest(path: Path) -> None:
    email_png = EVIDENCE / "supplier_email.png"
    carrier_pdf = EVIDENCE / "carrier_notice.pdf"
    mes_csv = EVIDENCE / "mes_snapshot.csv"
    payload = {
        "schema_version": "1.0",
        "case_as_of": "2026-08-25T10:00:00+08:00",
        "provenance": "Deterministic synthetic evidence overlay for the public-derived Mendeley case.",
        "license": "Apache-2.0",
        "derived_fields": ["OCR bounding box", "PDF line locator", "freshness flag", "delay conflict"],
        "seed": 20260825,
        "records": [
            {
                "evidence_id": "ev_supplier_email_png",
                "filename": email_png.name,
                "media_type": "image/png",
                "sha256": sha256_file(email_png),
                "observed_at": "2026-08-25T09:00:00+08:00",
                "freshness_hours": 8,
                "extraction_mode": "precomputed_ocr_fixture",
                "synthetic_boundary": "Rendered from supplier_email.eml; no real supplier or mailbox data.",
                "claims": [{
                    "field_name": "delay_hours",
                    "value": 48,
                    "unit": "hours",
                    "source_locator": "bbox(130,511,760,551)",
                    "quote": "cannot leave the facility for the next 48 hours"
                }]
            },
            {
                "evidence_id": "ev_carrier_notice_pdf",
                "filename": carrier_pdf.name,
                "media_type": "application/pdf",
                "sha256": sha256_file(carrier_pdf),
                "observed_at": "2026-08-25T09:15:00+08:00",
                "freshness_hours": 8,
                "extraction_mode": "pdf_text_layer",
                "synthetic_boundary": "Generated from carrier_notice_source.txt; not a real carrier document.",
                "claims": [{
                    "field_name": "delay_hours",
                    "value": 72,
                    "unit": "hours",
                    "source_locator": "page=1, text=Current arrival estimate",
                    "quote": "Current arrival estimate: 72 hours"
                }]
            },
            {
                "evidence_id": "ev_mes_snapshot_csv",
                "filename": mes_csv.name,
                "media_type": "text/csv",
                "sha256": sha256_file(mes_csv),
                "observed_at": "2026-08-24T08:00:00+08:00",
                "freshness_hours": 8,
                "extraction_mode": "csv_schema_parser",
                "synthetic_boundary": "Synthetic MES-like snapshot; not exported from a real system.",
                "claims": [{
                    "field_name": "delay_hours",
                    "value": 48,
                    "unit": "hours",
                    "source_locator": "row=2,column=eta_hours",
                    "quote": "eta_hours=48"
                }]
            }
        ]
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    build_email_png(EVIDENCE / "supplier_email.png")
    build_carrier_pdf(EVIDENCE / "carrier_notice.pdf")
    build_manifest(EVIDENCE / "manifest.json")
    print(json.dumps({
        "email_png": str(EVIDENCE / "supplier_email.png"),
        "carrier_pdf": str(EVIDENCE / "carrier_notice.pdf"),
        "manifest": str(EVIDENCE / "manifest.json"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
