#!/usr/bin/env python3
"""Fail-closed portable-package boundary check and checksum manifest builder."""
from __future__ import annotations
import hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"PACKAGE_MANIFEST.json"
SKIP_DIRS={".git",".venv","venv","__pycache__","node_modules","examiner-package","output","run"}
FORBIDDEN_SUFFIXES={".key",".pem",".pkl",".keras",".h5",".db",".sqlite",".dump",".backup",".zip",".7z"}
FORBIDDEN_NAMES={".env",".env.bak",".env.production"}
SECRET_PATTERNS=[re.compile(r"BEGIN (?:RSA |OPENSSH )?PRIVATE KEY"),re.compile(r"postgres(?:ql)?://[^\s:/]+:[^$<{\s][^@\s]*@",re.I)]

def digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
 return h.hexdigest()

def main():
 problems=[]; files=[]
 for path in sorted(ROOT.rglob("*")):
  rel=path.relative_to(ROOT)
  if path.is_dir() and path.name in {".venv","venv","__pycache__","node_modules","examiner-package","output","run"}:
   problems.append(f"generated/private directory: {rel}")
  if any(part in SKIP_DIRS for part in rel.parts):continue
  if not path.is_file() or path==MANIFEST:continue
  if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:problems.append(f"forbidden file: {rel}")
  if "tests" not in rel.parts and path.stat().st_size<=2_000_000 and path.suffix.lower() in {".py",".ps1",".sh",".yml",".yaml",".json",".env",".example"}:
   text=path.read_text(encoding="utf-8",errors="ignore")
   for pattern in SECRET_PATTERNS:
    if pattern.search(text) and "test_only@" not in text:problems.append(f"secret-like content: {rel}")
  files.append({"path":rel.as_posix(),"bytes":path.stat().st_size,"sha256":digest(path)})
 if problems:
  print("Package verification failed:\n- "+"\n- ".join(sorted(set(problems))),file=sys.stderr);return 1
 manifest={"schema_version":"1.0","generated_utc":datetime.now(timezone.utc).isoformat(),"classification":"public_code_and_synthetic_demo_only","empirical_data_included":False,"file_count":len(files),"files":files}
 MANIFEST.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
 print(f"Package verified: {len(files)} files; wrote {MANIFEST.name}");return 0
if __name__=="__main__":raise SystemExit(main())
