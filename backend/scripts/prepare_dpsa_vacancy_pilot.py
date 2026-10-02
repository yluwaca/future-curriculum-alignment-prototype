"""Prepare a traceable DPSA Public Service Vacancy Circular pilot CSV.

The output is suitable for the existing governed job-advert upload.  It does
not scrape an interactive job board: it transforms one explicitly supplied,
official circular PDF into one row per advertised post.  DPSA evidence is a
public-service vacancy proxy and must not be described as the whole labour
market.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pdfplumber


LABELS = (
    "SALARY",
    "CENTRE",
    "REQUIREMENTS",
    "DUTIES",
    "ENQUIRIES",
    "APPLICATIONS",
    "NOTE",
    "CLOSING DATE",
)

ICT_TITLE_TERMS = re.compile(
    r"\b(information (?:and communication )?technology|ict|it|software|developer|"
    r"programmer|data|database|systems?|network|cyber|digital|business analyst|"
    r"information management|computer|enterprise architect|solution architect)\b",
    re.I,
)
ICT_REQUIREMENT_TERMS = re.compile(
    r"\b(programming|software development|database administration|data science|"
    r"cybersecurity|network administration|systems analysis|cloud computing|"
    r"information systems|computer science|information technology)\b",
    re.I,
)


def compact(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def labelled(block: str, label: str) -> str:
    next_labels = "|".join(re.escape(item) for item in LABELS if item != label)
    match = re.search(
        rf"(?ms)^\s*{re.escape(label)}\s*:?[ \t]*(.*?)(?=^\s*(?:{next_labels})\s*:?|\Z)",
        block,
    )
    return compact(match.group(1)) if match else ""


def parse_date(text: str) -> str:
    match = re.search(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(20\d{2})\b",
        text,
        re.I,
    )
    if not match:
        return ""
    return datetime.strptime(" ".join(match.groups()), "%d %B %Y").date().isoformat()


@dataclass
class Vacancy:
    job_id: str
    job_title: str
    company: str
    region: str
    country: str
    description: str
    requirements: str
    skills: str
    salary: str
    posted_date: str
    closed_date: str
    source: str
    source_url: str
    circular: str
    source_page: int
    source_sha256: str
    evidence_role: str = "public_service_vacancy_proxy"
    sector_scope: str = "South African public service"
    representativeness_note: str = (
        "Not representative of all Western Cape or private-sector ICT vacancies"
    )


def parse_pdf(
    pdf_path: Path,
    source_url: str,
    circular: str,
    issued_date: str,
    start_page: int,
    end_page: int | None,
    ict_only: bool,
) -> list[Vacancy]:
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    vacancies: list[Vacancy] = []
    with pdfplumber.open(pdf_path) as pdf:
        final_page = min(end_page or len(pdf.pages), len(pdf.pages))
        document = "".join(
            f"\n<<<PAGE:{page_number}>>>\n{pdf.pages[page_number - 1].extract_text() or ''}"
            for page_number in range(start_page, final_page + 1)
        )
    # PDF layout extraction occasionally places field labels mid-line.  Restore
    # structural newlines before parsing while leaving the retained PDF intact.
    label_pattern = "|".join(re.escape(item) for item in LABELS)
    document = re.sub(rf"\s+(?=({label_pattern})\s*:?)", "\n", document)

    starts = list(re.finditer(r"(?m)^\s*POST\s+([0-9]{1,2}/[0-9]{1,3})\s*:\s*", document))
    for index, start in enumerate(starts):
        block = document[start.start() : starts[index + 1].start() if index + 1 < len(starts) else None]
        reference = start.group(1)
        title_area = block[start.end() - start.start() :]
        title = compact(re.split(r"(?m)^\s*SALARY\s*:?[ \t]*", title_area, maxsplit=1)[0])
        title = re.sub(r"<<<PAGE:\d+>>>", "", title).strip()
        requirements = re.sub(r"<<<PAGE:\d+>>>", "", labelled(block, "REQUIREMENTS")).strip()
        duties = re.sub(r"<<<PAGE:\d+>>>", "", labelled(block, "DUTIES")).strip()
        centre = re.sub(r"<<<PAGE:\d+>>>", "", labelled(block, "CENTRE")).strip() or "Western Cape"
        if ict_only and not ICT_TITLE_TERMS.search(title):
            continue
        prefix = document[: start.start()]
        page_matches = list(re.finditer(r"<<<PAGE:(\d+)>>>", prefix))
        page_number = int(page_matches[-1].group(1)) if page_matches else start_page
        dept_matches = list(
            re.finditer(r"(?m)^\s*(?:WESTERN CAPE\s+)?(?:DEPARTMENT|VOTE)\s+OF\s+[^\n]+", prefix)
        )
        department = compact(dept_matches[-1].group(0)) if dept_matches else "Western Cape Provincial Administration"
        closing_matches = list(re.finditer(r"(?m)^\s*CLOSING DATE\s*:?[ \t]*([^\n]+)", prefix))
        active_closing_date = parse_date(closing_matches[-1].group(1)) if closing_matches else ""
        block_closing = parse_date(labelled(block, "CLOSING DATE")) or active_closing_date
        vacancies.append(
            Vacancy(
                job_id=f"DPSA-{circular.replace('/', '-')}-{reference.replace('/', '-')}",
                job_title=title,
                company=department,
                region=f"Western Cape | {centre}",
                country="ZA",
                description=duties,
                requirements=requirements,
                skills="",
                salary=labelled(block, "SALARY"),
                posted_date=issued_date,
                closed_date=block_closing,
                source="DPSA Public Service Vacancy Circular",
                source_url=f"{source_url}#page={page_number}",
                circular=circular,
                source_page=page_number,
                source_sha256=digest,
            )
        )
    return vacancies


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--circular", required=True, help="For example 11/2026")
    parser.add_argument("--issued-date", required=True, help="ISO date")
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--all-posts", action="store_true", help="Do not restrict output to ICT candidates")
    args = parser.parse_args()

    rows = parse_pdf(
        args.pdf,
        args.source_url,
        args.circular,
        args.issued_date,
        args.start_page,
        args.end_page,
        not args.all_posts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(Vacancy.__dataclass_fields__)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)

    manifest = {
        "source_url": args.source_url,
        "source_file": str(args.pdf),
        "source_sha256": hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
        "circular": args.circular,
        "issued_date": args.issued_date,
        "page_scope": [args.start_page, args.end_page],
        "filter": "all posts" if args.all_posts else "ICT candidate rule v1",
        "records": len(rows),
        "evidence_role": "public_service_vacancy_proxy",
        "representativeness": "Not the entire Western Cape or private-sector ICT labour market",
        "generated_at": datetime.now().astimezone().isoformat(),
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
