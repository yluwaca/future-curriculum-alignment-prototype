"""Render an immutable FUTURE committee-pack API record as an examiner-ready PDF."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def api_json(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FUTURE API returned HTTP {exc.code}: {detail}") from exc


def text(value) -> str:
    if value is None or value == "":
        return "-"
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(report: dict, destination: Path) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TitleCentre", parent=styles["Title"], alignment=TA_CENTER,
        textColor=colors.HexColor("#163A63"), fontSize=18, leading=22, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#163A63"),
        fontSize=13, leading=16, spaceBefore=8, spaceAfter=6, keepWithNext=0,
    ))
    styles.add(ParagraphStyle(
        name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11,
    ))
    styles.add(ParagraphStyle(
        name="Notice", parent=styles["BodyText"], fontSize=9, leading=12,
        textColor=colors.HexColor("#6B4F00"), backColor=colors.HexColor("#FFF8D8"),
        borderColor=colors.HexColor("#E9C46A"), borderWidth=0.5, borderPadding=7,
    ))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D8E1EA"))
        canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5F6F7F"))
        canvas.drawString(18 * mm, 9 * mm, "FUTURE - governed curriculum-labour decision support")
        canvas.drawRightString(192 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    destination.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(destination), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=17 * mm, bottomMargin=19 * mm,
        title="FUTURE Curriculum Recommendation Evidence Pack",
        author="FUTURE Platform",
    )
    payload = report.get("payload") or {}
    items = payload.get("recommendations") or []
    story = [
        Paragraph("FUTURE Curriculum Recommendation Evidence Pack", styles["TitleCentre"]),
        Paragraph("Final governed recommendation evidence for examination and committee review", styles["Heading3"]),
        Spacer(1, 3 * mm),
        Table([
            [Paragraph("Report ID", styles["Small"]), Paragraph(text(report.get("report_id")), styles["Small"])],
            [Paragraph("Created", styles["Small"]), Paragraph(text(report.get("created_at")), styles["Small"])],
            [Paragraph("Evidence-pack SHA-256", styles["Small"]), Paragraph(text(report.get("payload_hash")), styles["Small"])],
            [Paragraph("Source manifest", styles["Small"]), Paragraph(text(payload.get("source_manifest_report_id")), styles["Small"])],
            [Paragraph("Source-manifest SHA-256", styles["Small"]), Paragraph(text(payload.get("source_manifest_hash")), styles["Small"])],
            [Paragraph("Eligible recommendations", styles["Small"]), Paragraph(str(len(items)), styles["Small"])],
        ], colWidths=[44 * mm, 125 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FA")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCD8E5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])),
        Spacer(1, 4 * mm),
        Paragraph(
            "Decision-support evidence only. Recommendations identify evidence warranting human attention; "
            "they do not automatically establish curriculum relevance, feasibility, accreditation impact, "
            "resource availability, or a committee decision.", styles["Notice"]),
        Spacer(1, 5 * mm),
        Paragraph("Executive summary", styles["Section"]),
        Paragraph(
            f"The portal governance gates found {len(items)} recommendation(s) eligible for this immutable "
            "committee evidence pack. Each included item has validated regeneration provenance, a documented "
            "human review and a supporting explanation. The review events below preserve the reviewer, role, "
            "decision, reason, timestamp and evidence-context fingerprint.", styles["BodyText"]),
    ]

    for index, item in enumerate(items, start=1):
        rec = item.get("recommendation") or {}
        reviews = item.get("human_reviews") or []
        explanations = item.get("explanations") or []
        story.extend([
            PageBreak() if index > 1 else Spacer(1, 4 * mm),
            Paragraph(f"Recommendation {index}: {text(rec.get('title') or 'Untitled recommendation')}", styles["Section"]),
            Table([
                ["Recommendation ID", text(rec.get("recommendation_id"))],
                ["Status", text(rec.get("status"))],
                ["Priority", text(rec.get("priority"))],
                ["Priority score", text(rec.get("priority_score"))],
                ["Confidence score", text(rec.get("confidence_score"))],
                ["Recommendation type", text(rec.get("recommendation_type"))],
                ["Created / updated", f"{text(rec.get('created_at'))} / {text(rec.get('updated_at'))}"],
            ], colWidths=[43 * mm, 126 * mm], style=TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF4FA")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD8E5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ])),
            Spacer(1, 3 * mm),
            Paragraph("Recommendation", styles["Heading3"]),
            Paragraph(text(rec.get("description")), styles["BodyText"]),
            Spacer(1, 3 * mm),
            Paragraph("Human review and audit trail", styles["Heading3"]),
        ])
        for review in reviews:
            meta = review.get("review_metadata") or {}
            review_rows = [
                ["Decision", text(review.get("decision"))],
                ["Status transition", f"{text(review.get('previous_status'))} -> {text(review.get('new_status'))}"],
                ["Reviewer", text(review.get("reviewer_id"))],
                ["Reviewer role", text(meta.get("reviewer_role"))],
                ["Timestamp", text(review.get("created_at"))],
                ["Reason", text(review.get("decision_reason"))],
                ["Feedback", text(review.get("feedback_comment"))],
                ["Evidence reviewed", "Yes" if meta.get("evidence_reviewed") is True else "No"],
                ["Evidence fingerprint", text(meta.get("evidence_context_fingerprint"))],
                ["Dataset identity", text(
                    meta.get("dataset_fingerprint")
                    or meta.get("reviewed_label_snapshot_version")
                    or payload.get("source_manifest_hash")
                )],
                ["Source", text(
                    meta.get("source_type")
                    or f"Validated evidence regeneration manifest {payload.get('source_manifest_report_id') or '-'}"
                )],
                ["Provenance", text(
                    meta.get("provenance")
                    or "Legacy review fingerprint anchored to the immutable source manifest in this committee pack"
                )],
            ]
            story.append(Table(
                [[Paragraph(text(a), styles["Small"]), Paragraph(text(b), styles["Small"])] for a, b in review_rows],
                colWidths=[43 * mm, 126 * mm], repeatRows=0,
                style=TableStyle([
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F6F8FA")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D8E1EA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ])))
            story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Supporting explanation", styles["Heading3"]))
        if explanations:
            for explanation in explanations:
                explanation_text = explanation.get("explanation_text") or explanation.get("explanation") or explanation.get("summary")
                story.append(Paragraph(text(explanation_text or json.dumps(explanation, sort_keys=True)), styles["Small"]))
                story.append(Spacer(1, 2 * mm))
        else:
            story.append(Paragraph("No separate explanation record was returned.", styles["Small"]))
        for limitation in item.get("limitations") or []:
            story.append(Paragraph(f"Limitation: {text(limitation)}", styles["Notice"]))
            story.append(Spacer(1, 2 * mm))

    story.append(KeepTogether([
        Spacer(1, 5 * mm),
        Paragraph("Governance statement", styles["Section"]),
        Paragraph(text((payload.get("governance") or {}).get("decision_authority")), styles["BodyText"]),
        Spacer(1, 3 * mm),
        Paragraph(
            "This pack preserves system-generated recommendations and human review records. It is evidence for "
            "deliberation, not evidence that a curriculum change was implemented or empirically validated across "
            "institutions. Institutional feasibility and formal academic governance remain outside the automated model.",
            styles["Notice"],
        ),
    ]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    login = api_json(
        f"{args.base_url.rstrip('/')}/api/v1/auth/login",
        method="POST",
        payload={"identifier": args.username, "password": args.password},
    )
    report = api_json(
        f"{args.base_url.rstrip('/')}/api/v1/analytics/reports/{args.report_id}",
        token=login["access_token"],
    )
    build_pdf(report, args.output)
    print(json.dumps({
        "output": str(args.output.resolve()),
        "report_id": report.get("report_id"),
        "payload_hash": report.get("payload_hash"),
        "recommendations": len((report.get("payload") or {}).get("recommendations") or []),
    }))


if __name__ == "__main__":
    main()
