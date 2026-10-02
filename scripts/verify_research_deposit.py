#!/usr/bin/env python3
"""Verify the structure and SHA-256 register of a research deposit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = {
    "dataset/alignment_observations.csv",
    "metadata/dataset_manifest.json",
    "splits/split_membership.csv",
    "evaluation/predictions.csv",
    "evaluation/metrics.json",
    "evaluation/candidate_evaluation.json",
    "model/model_card.json",
    "model/model_parameters.json",
    "model/feature_specification.json",
    "PACKAGE_MANIFEST.json",
    "SHA256SUMS.txt",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    root = args.package.resolve()
    problems: list[str] = []

    for relative in sorted(REQUIRED):
        if not (root / relative).is_file():
            problems.append(f"missing required file: {relative}")

    checksum_path = root / "SHA256SUMS.txt"
    if checksum_path.is_file():
        for line_number, line in enumerate(
            checksum_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                expected, relative = line.split("  ", 1)
            except ValueError:
                problems.append(f"invalid checksum line {line_number}")
                continue
            path = root / relative
            if not path.is_file():
                problems.append(f"checksum target missing: {relative}")
            elif sha256(path) != expected:
                problems.append(f"checksum mismatch: {relative}")

    manifest_path = root / "PACKAGE_MANIFEST.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"invalid package manifest: {error}")
        else:
            if not manifest.get("snapshot_id"):
                problems.append("package manifest has no snapshot_id")
            if not manifest.get("candidate_id"):
                problems.append("package manifest has no candidate_id")

    if problems:
        print("Deposit verification failed:\n- " + "\n- ".join(problems))
        return 1
    print("Deposit verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

