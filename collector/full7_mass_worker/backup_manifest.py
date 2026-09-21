#!/usr/bin/env python3
"""Create a non-destructive SHA-256 inventory for the FULL-7 persistent data tree."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_ROOT = Path(os.environ.get("FULL7_DATA_ROOT", "/var/data/full7"))
OUT_TSV = DATA_ROOT / "FULL7_BACKUP_SHA256_MANIFEST.tsv"
OUT_JSON = DATA_ROOT / "FULL7_BACKUP_INVENTORY.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if not DATA_ROOT.is_dir():
        raise SystemExit(f"missing data root: {DATA_ROOT}")

    excluded = {OUT_TSV.resolve(), OUT_JSON.resolve()}
    files = [
        p for p in DATA_ROOT.rglob("*")
        if p.is_file() and p.resolve() not in excluded
    ]
    files.sort(key=lambda p: str(p.relative_to(DATA_ROOT)))

    total_bytes = 0
    rows = []
    tmp = OUT_TSV.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as out:
        out.write("sha256\tsize_bytes\trelative_path\n")
        for idx, path in enumerate(files, 1):
            size = path.stat().st_size
            digest = sha256_file(path)
            rel = str(path.relative_to(DATA_ROOT))
            total_bytes += size
            out.write(f"{digest}\t{size}\t{rel}\n")
            if idx % 1000 == 0:
                print({"inventory_files": idx, "total_files": len(files)}, flush=True)
    tmp.replace(OUT_TSV)

    manifest_sha = sha256_file(OUT_TSV)
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_root": str(DATA_ROOT),
        "file_count_excluding_manifest_outputs": len(files),
        "total_bytes_excluding_manifest_outputs": total_bytes,
        "sha256_manifest": str(OUT_TSV),
        "sha256_manifest_sha256": manifest_sha,
        "policy": "NON_DESTRUCTIVE_INVENTORY_ONLY",
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("BACKUP_INVENTORY", json.dumps(summary, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
