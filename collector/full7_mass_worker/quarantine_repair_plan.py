#!/usr/bin/env python3
"""Build a read-only quarantine repair plan from existing reason.json files."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("FULL7_ROOT", "/var/data/full7/output"))
QUAR = ROOT / "quarantine"
OUT = ROOT / "FULL7_QUARANTINE_REPAIR_PLAN.json"


def classify(reasons: list[str]) -> str:
    text = " | ".join(str(x) for x in reasons)
    if "417 Client Error: Expectation Failed" in text:
        return "HTTP_417"
    if any(str(x).startswith("league_source_count_mismatch:") for x in reasons):
        return "LEAGUE_SOURCE_COUNT_MISMATCH"
    return "OTHER"


def main() -> None:
    if not QUAR.is_dir():
        raise SystemExit(f"missing quarantine dir: {QUAR}")

    rows = []
    class_counts = Counter()
    season_counts = Counter()
    season_by_class = defaultdict(Counter)
    reason_counts = Counter()

    for rp in sorted(QUAR.glob("*/reason.json")):
        try:
            obj = json.loads(rp.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append({
                "match_id": rp.parent.name,
                "class": "UNREADABLE_REASON",
                "error": f"{type(exc).__name__}:{exc}",
            })
            class_counts["UNREADABLE_REASON"] += 1
            continue

        reasons = obj.get("reason_if_false") or ["UNKNOWN"]
        if not isinstance(reasons, list):
            reasons = [str(reasons)]
        cls = classify(reasons)
        mid = obj.get("match_id") or rp.parent.name
        sid = obj.get("season_id")
        rows.append({
            "match_id": int(mid) if str(mid).isdigit() else mid,
            "season_id": sid,
            "class": cls,
            "reasons": reasons,
        })
        class_counts[cls] += 1
        season_counts[str(sid)] += 1
        season_by_class[cls][str(sid)] += 1
        for reason in reasons:
            reason_counts[str(reason)] += 1

    report = {
        "policy": "READ_ONLY_PLAN_NO_RECLASSIFICATION_NO_REPLAY",
        "total": len(rows),
        "class_counts": dict(class_counts),
        "season_counts": dict(sorted(season_counts.items())),
        "season_by_class": {
            cls: dict(sorted(counts.items()))
            for cls, counts in sorted(season_by_class.items())
        },
        "reason_counts": dict(sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "matches": rows,
        "required_next_step": {
            "HTTP_417": "backup first, rotate/redact API key, restore exact league access, replay only these match_ids with identical strict cutoff/rules",
            "LEAGUE_SOURCE_COUNT_MISMATCH": "provenance audit; never auto-accept or add tolerance without demonstrated provider counting semantics",
            "OTHER": "manual strict provenance audit",
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("QUARANTINE_REPAIR_PLAN", json.dumps({
        "total": report["total"],
        "class_counts": report["class_counts"],
        "season_by_class": report["season_by_class"],
        "out": str(OUT),
    }, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
