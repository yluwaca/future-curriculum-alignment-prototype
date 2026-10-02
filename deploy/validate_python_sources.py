#!/usr/bin/env python3
"""Parse packaged Python sources without creating bytecode or cache directories."""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "backend" / "app"
    failures: list[str] = []
    count = 0
    for source in sorted(root.rglob("*.py")):
        count += 1
        try:
            # utf-8-sig accepts ordinary UTF-8 and strips the optional BOM that
            # Python's source loader also permits at the start of a module.
            ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        except (OSError, SyntaxError, UnicodeError) as exc:
            failures.append(f"{source.relative_to(root)}: {exc}")
    if failures:
        print("Python source validation failed:\n- " + "\n- ".join(failures), file=sys.stderr)
        return 1
    print(f"Python source syntax validated: {count} files; no bytecode generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
