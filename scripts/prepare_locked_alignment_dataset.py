#!/usr/bin/env python3
"""Create a deidentified, technology-neutral derivative of a FUTURE label export."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def digest_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pseudonym(prefix: str, namespace: str, value: str) -> str:
    return f"{prefix}_{digest_bytes(namespace + '|' + value)[:20]}"


def as_int(value: str, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid integer in {field}: {value!r}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--snapshot-version", required=True)
    parser.add_argument("--snapshot-fingerprint", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--target-threshold", type=float, default=0.35)
    args = parser.parse_args()

    required = {
        "row_index",
        "task_id",
        "version_id",
        "document_id",
        "dataset_mode",
        "subject_code",
        "stratum",
        "sample_seed",
        "final_alignment_label",
        "first_reviewer_id",
        "first_label",
        "first_confidence",
        "second_reviewer_id",
        "second_label",
        "second_confidence",
        "agreement",
    }
    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise SystemExit("input contains no rows")

    namespace = args.snapshot_fingerprint
    reviewer_values = sorted(
        {
            row[field]
            for row in rows
            for field in ("first_reviewer_id", "second_reviewer_id")
            if row[field].strip()
        }
    )
    reviewer_map = {
        value: f"reviewer_{index:03d}" for index, value in enumerate(reviewer_values, start=1)
    }

    output_rows: list[dict[str, object]] = []
    label_counts: Counter[int] = Counter()
    target_counts: Counter[int] = Counter()
    for row in rows:
        label = as_int(row["final_alignment_label"], "final_alignment_label")
        if label not in {1, 2, 3, 4, 5}:
            raise SystemExit(f"label outside 1-5 scale: {label}")
        normalised_score = (label - 1) / 4
        target = int(normalised_score >= args.target_threshold)
        label_counts[label] += 1
        target_counts[target] += 1
        first_reviewer = row["first_reviewer_id"].strip()
        second_reviewer = row["second_reviewer_id"].strip()
        reviewer_count = int(bool(first_reviewer)) + int(bool(second_reviewer))
        output_rows.append(
            {
                "row_index": as_int(row["row_index"], "row_index"),
                "observation_id": pseudonym("obs", namespace, row["task_id"]),
                "group_id": pseudonym("grp", namespace, row["document_id"]),
                "version_id_hash": pseudonym("ver", namespace, row["version_id"]),
                "source_document_hash": digest_bytes(namespace + "|" + row["document_id"]),
                "dataset_mode": row["dataset_mode"],
                "subject_code": row["subject_code"],
                "stratum": row["stratum"],
                "sample_seed": row["sample_seed"],
                "final_alignment_label": label,
                "normalised_alignment_score": f"{normalised_score:.2f}",
                "target_threshold": f"{args.target_threshold:.2f}",
                "binary_target": target,
                "label_basis": "transparent_rule_assisted_portal_confirmation",
                "coding_protocol_version": "not_present_in_snapshot_export",
                "first_reviewer_pseudonym": reviewer_map.get(first_reviewer, ""),
                "first_label": row["first_label"],
                "first_confidence": row["first_confidence"],
                "second_reviewer_pseudonym": reviewer_map.get(second_reviewer, ""),
                "second_label": row["second_label"],
                "second_confidence": row["second_confidence"],
                "reviewer_count": reviewer_count,
                "independent_reviewers": "false",
                "adjudication_complete": "false",
                "agreement_recorded": row["agreement"],
                "eligible_for_reported_candidate_run": "true",
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    manifest = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_version": args.snapshot_version,
        "snapshot_fingerprint_displayed": args.snapshot_fingerprint,
        "candidate_version": args.candidate_version,
        "source_export": {
            "filename": args.input.name,
            "sha256": digest_file(args.input),
            "records": len(rows),
        },
        "deidentified_dataset": {
            "filename": args.output.name,
            "sha256": digest_file(args.output),
            "records": len(output_rows),
            "identifier_policy": "operational UUIDs replaced with snapshot-scoped pseudonyms; reviewer IDs replaced with ordinal pseudonyms; mapping not retained",
        },
        "label_basis": "transparent_rule_assisted_portal_confirmation",
        "independent_expert_labels": False,
        "label_counts": {str(key): label_counts[key] for key in sorted(label_counts)},
        "target_definition": "binary_target = 1 when (final_alignment_label - 1) / 4 >= 0.35; otherwise 0",
        "target_counts": {str(key): target_counts[key] for key in sorted(target_counts)},
        "redistribution_status": "review_required_before_public_release",
        "limitations": [
            "The snapshot represents researcher-confirmed transparent rule-assisted labels, not independent expert labels.",
            "The export does not contain curriculum or labour-market source text, evidence dates, source-rights decisions, fold membership, predictions or model parameters.",
            "The exported agreement field must not be interpreted as inter-rater agreement because no second reviewer is present in this snapshot.",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(rows), "labels": manifest["label_counts"], "targets": manifest["target_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

