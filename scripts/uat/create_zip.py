#!/usr/bin/env python3
"""
create_zip.py - Creates a Linux-compatible zip from the UAT folder.

Root cause: PowerShell's Compress-Archive uses backslashes in zip paths.
Linux unzip treats these as literal characters, breaking the extraction.

This script uses Python's zipfile module with forward-slash arcnames.

Usage:
    python scripts/uat/create_zip.py
    python scripts/uat/create_zip.py --source C:/projects/uat --output C:/projects/uat/future-uat.zip
"""

import zipfile
import os
import sys
import argparse


def create_linux_zip(source_dir: str, output_path: str) -> None:
    exclude_dirs = {"_backup_", "__pycache__", ".git", "node_modules", ".pytest_cache"}
    exclude_files = {".pyc", ".pyo", ".bat", ".ps1", ".exe", ".pyd", ".zip"}
    exclude_names = {"future-uat.zip"}

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        count = 0
        for root, dirs, files in os.walk(source_dir):
            # Filter excluded directories in-place
            dirs[:] = [d for d in dirs if not any(ex in d for ex in exclude_dirs)]

            for fname in files:
                # Skip excluded file types
                if any(fname.endswith(ex) for ex in exclude_files):
                    continue
                if any(ex in fname for ex in exclude_dirs):
                    continue
                if fname in exclude_names:
                    continue

                filepath = os.path.join(root, fname)
                # Convert backslashes to forward slashes, strip leading source dir
                arcname = os.path.relpath(filepath, source_dir).replace(os.sep, "/")
                zf.write(filepath, arcname)
                count += 1

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Created: {output_path}")
    print(f"Files:   {count}")
    print(f"Size:    {size_mb:.1f} MB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Linux-compatible zip for UAT deployment")
    parser.add_argument("--source", default=r"C:\projects\uat", help="Source directory (default: C:\\projects\\uat)")
    parser.add_argument("--output", default=None, help="Output zip path (default: <source>/future-uat.zip)")
    args = parser.parse_args()

    source = args.source
    output = args.output or os.path.join(source, "future-uat.zip")

    if not os.path.isdir(source):
        print(f"ERROR: Source directory not found: {source}")
        sys.exit(1)

    create_linux_zip(source, output)
