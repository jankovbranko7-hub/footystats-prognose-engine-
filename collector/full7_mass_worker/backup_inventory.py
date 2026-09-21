#!/usr/bin/env python3
"""Create a cryptographic inventory of the FULL-7 collection without archiving it.

Writes a small manifest under ROOT/final_audit. It does not modify collector data.
The manifest can be used to verify a later external byte-for-byte copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("FULL7_ROOT", "/var/data/full7/output"))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out = root / "final_audit"
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "file_manifest_sha256.jsonl"
    summary_path = out / "file_manifest_summary.json"

    excluded = {
        manifest_path.resolve(),
        summary_path.resolve(),
    }

    files = [p for p in root.rglob("*") if p.is_file() and p.resolve() not in excluded]
    files.sort(key=lambda p: p.relative_to(root).as_posix())

    tree = hashlib.sha256()
    total_bytes = 0
    count = 0
    categories = {}
    with manifest_path.open("w", encoding="utf-8") as fh:
        for p in files:
            rel = p.relative_to(root).as_posix()
            size = p.stat().st_size
            digest = sha256_file(p)
            rec = {"path": rel, "size": size, "sha256": digest}
            fh.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
            tree.update(f"{rel}\0{size}\0{digest}\n".encode("utf-8"))
            total_bytes += size
            count += 1
            top = rel.split("/", 1)[0]
            cur = categories.setdefault(top, {"files": 0, "bytes": 0})
            cur["files"] += 1
            cur["bytes"] += size
            if count % 5000 == 0:
                print({"files": count, "bytes": total_bytes}, flush=True)

    summary = {
        "inventory_version": "FULL7_FILE_MANIFEST_1.0",
        "root": str(root),
        "file_count": count,
        "total_bytes": total_bytes,
        "tree_sha256": tree.hexdigest(),
        "manifest_file": manifest_path.name,
        "manifest_sha256": sha256_file(manifest_path),
        "categories": categories,
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
