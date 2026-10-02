#!/usr/bin/env python3
"""Build an integrity-registered examiner/eSango deposit from explicit inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "path": destination.as_posix(),
        "bytes": destination.stat().st_size,
        "sha256": sha256(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--dataset-manifest", type=Path, required=True)
    parser.add_argument("--split-membership", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--candidate-evaluation", type=Path, required=True)
    parser.add_argument("--model-card", type=Path, required=True)
    parser.add_argument("--model-parameters", type=Path, required=True)
    parser.add_argument("--feature-specification", type=Path, required=True)
    parser.add_argument("--committee-report", type=Path)
    parser.add_argument("--screenshot", type=Path, action="append", default=[])
    args = parser.parse_args()

    required = [
        args.dataset,
        args.dataset_manifest,
        args.split_membership,
        args.predictions,
        args.metrics,
        args.candidate_evaluation,
        args.model_card,
        args.model_parameters,
        args.feature_specification,
    ]
    optional = ([args.committee_report] if args.committee_report else []) + args.screenshot
    missing = [str(path) for path in required + optional if not path.is_file()]
    if missing:
        raise SystemExit("Missing input files:\n- " + "\n- ".join(missing))

    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Output must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    mappings = [
        (args.dataset, Path("dataset/alignment_observations.csv")),
        (args.dataset_manifest, Path("metadata/dataset_manifest.json")),
        (args.split_membership, Path("splits/split_membership.csv")),
        (args.predictions, Path("evaluation/predictions.csv")),
        (args.metrics, Path("evaluation/metrics.json")),
        (args.candidate_evaluation, Path("evaluation/candidate_evaluation.json")),
        (args.model_card, Path("model/model_card.json")),
        (args.model_parameters, Path("model/model_parameters.json")),
        (args.feature_specification, Path("model/feature_specification.json")),
    ]
    if args.committee_report:
        mappings.append((args.committee_report, Path("evidence/committee_report.pdf")))
    mappings.extend(
        (path, Path("evidence/screenshots") / path.name) for path in args.screenshot
    )

    files: list[dict[str, object]] = []
    for source, relative_destination in mappings:
        record = copy_file(source.resolve(), output / relative_destination)
        record["path"] = relative_destination.as_posix()
        files.append(record)

    manifest = {
        "schema_version": "1.0",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": args.snapshot_id,
        "candidate_id": args.candidate_id,
        "classification": "controlled_examiner_esango_research_package",
        "files": files,
    }
    manifest_path = output / "PACKAGE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    checksum_records = files + [
        {
            "path": "PACKAGE_MANIFEST.json",
            "sha256": sha256(manifest_path),
        }
    ]
    checksum_text = "".join(
        f"{record['sha256']}  {record['path']}\n"
        for record in sorted(checksum_records, key=lambda item: str(item["path"]))
    )
    (output / "SHA256SUMS.txt").write_text(checksum_text, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

