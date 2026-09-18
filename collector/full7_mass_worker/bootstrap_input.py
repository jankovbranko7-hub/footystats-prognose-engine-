#!/usr/bin/env python3
"""Reconstruct and verify the immutable 17,685-target manifest on persistent disk."""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import os
from pathlib import Path

EXPECTED_ROWS = 17685
EXPECTED_RAW_SHA256 = "6f8d79f8bb477b8d7e1735a6e61a57e1f3ba998ca65af8aab903094bb64d5b65"
EXPECTED_GZIP_SHA256 = "fac6a033afb670e5002ac64e36b92fedd36719e89b55c35d2e975aead5998069"

HERE = Path(__file__).resolve().parent
PART_DIR = HERE / "input"
DEST = Path(os.environ.get("FULL7_CSV", str(HERE / "input" / "full7_targets_17685_min.csv")))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_csv_bytes(raw: bytes) -> None:
    if sha256(raw) != EXPECTED_RAW_SHA256:
        raise RuntimeError("target manifest raw SHA256 mismatch")
    text = raw.decode("utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    if len(rows) != EXPECTED_ROWS:
        raise RuntimeError(f"target manifest row count {len(rows)} != {EXPECTED_ROWS}")
    if set(rows[0].keys() if rows else []) != {"match_id", "season_id"}:
        raise RuntimeError("target manifest columns mismatch")
    ids = [row["match_id"] for row in rows]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("target manifest has empty/duplicate match_id")


def main() -> None:
    parts = sorted(PART_DIR.glob("targets.b64.part*"))
    if len(parts) != 7:
        raise RuntimeError(f"expected 7 manifest parts, found {len(parts)}")

    b64 = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    gz = base64.b64decode(b64, validate=True)
    if sha256(gz) != EXPECTED_GZIP_SHA256:
        raise RuntimeError("target manifest gzip SHA256 mismatch")
    raw = gzip.decompress(gz)
    validate_csv_bytes(raw)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists():
        validate_csv_bytes(DEST.read_bytes())
        print(f"MANIFEST_OK existing={DEST} rows={EXPECTED_ROWS} sha256={EXPECTED_RAW_SHA256}", flush=True)
        return

    tmp = DEST.with_suffix(DEST.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(DEST)
    print(f"MANIFEST_READY path={DEST} rows={EXPECTED_ROWS} sha256={EXPECTED_RAW_SHA256}", flush=True)


if __name__ == "__main__":
    main()
