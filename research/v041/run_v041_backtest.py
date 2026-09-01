#!/usr/bin/env python3
"""Replay the frozen v0.4.1 decision gate on clean v0.4.0 archives."""

from __future__ import annotations

import csv
import json
import math
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from v041_decision_gate import VERSION, evaluate_v041


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    half = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return round(max(0, centre - half) * 100, 2), round(min(1, centre + half) * 100, 2)


def rate(rows: list[dict]) -> dict:
    hits = sum(bool(row["strongest_market_hit"]) for row in rows)
    low, high = wilson(hits, len(rows))
    return {
        "n": len(rows),
        "hits": hits,
        "hit_rate_pct": round(hits / len(rows) * 100, 2) if rows else None,
        "wilson_95_low_pct": low,
        "wilson_95_high_pct": high,
    }


def grouped(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return [{key: name, **rate(items)} for name, items in sorted(groups.items())]


def make_report(summary: dict) -> str:
    play = summary["v041"]["spielen"]
    lines = [
        "# FootyStats v0.4.1 – Offline-Gate-Test",
        "",
        "## Zweck",
        "",
        "Die Wahrscheinlichkeiten der v0.4.0 bleiben unverändert. Nur die strukturell blockierte Entscheidungsebene wird repariert. Die Live-App, GitHub und Render wurden nicht verändert.",
        "",
        "## Eingefrorene Änderungen",
        "",
        "1. Relative Edge wird nur gegen den direkt widersprechenden Ausgang desselben Marktes berechnet.",
        "2. Eine niedrige Frühphasen-Stichprobe darf nur dann kompensiert werden, wenn Empirical-Bayes-Shrinkage aktiv ist und alle übrigen Qualitäts-, Multi-Block-, Underlying-, Kohärenz- und Removal-Prüfungen bestehen.",
        "3. Die SPIELEN-Schwelle bleibt bei mindestens 65 %.",
        "4. Starke Gegenargumente, starke Underlying-Widersprüche oder ein Single Point of Failure bleiben Sperren.",
        "",
        "## Vergleich auf 102 sauberen Vor-Spiel-Analysen",
        "",
        f"- v0.4.0 SPIELEN: **{summary['v040']['spielen']['n']}**",
        f"- v0.4.1 SPIELEN: **{play['n']}**",
        f"- Treffer der v0.4.1-SPIELEN-Auswahl: **{play['hits']}/{play['n']} ({play['hit_rate_pct']} %)**",
        f"- 95-%-Wilson-Intervall: **{play['wilson_95_low_pct']}–{play['wilson_95_high_pct']} %**",
        "",
        "## Kandidaten",
        "",
        "| Datum | Spiel | Markt | Modell | Ergebnis | Treffer |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in summary["v041"]["spielen_candidates"]:
        lines.append(
            f"| {item['date']} | {item['home_name']} – {item['away_name']} | {item['strongest_market']} | {item['strongest_probability_pct']} % | {item['actual_score']} | {'JA' if item['strongest_market_hit'] else 'NEIN'} |"
        )
    lines += [
        "",
        "## Bewertung",
        "",
        "Das Ergebnis zeigt, dass die korrigierte Entscheidungsebene wieder selektieren kann. Es ist noch keine endgültige Produktionsfreigabe: Die acht SPIELEN-Fälle stammen aus demselben Diagnosezeitraum und das Konfidenzintervall ist breit. Die Regel ist nun eingefroren und muss unverändert an neuen, chronologisch späteren Spielen bestätigt werden.",
        "",
        "## Integrität",
        "",
        "- Der Gate-Code erhält ausschließlich gespeicherte Pre-Match-Analysen.",
        "- Endstände werden erst nach der Entscheidung zum Auswerten verbunden.",
        "- Keine Quoten, kein Value und keine externen Matchinformationen fließen in die Entscheidung ein.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("Usage: run_v041_backtest.py INPUT_ZIP INVENTORY_JSON RESULTS_JSON OUTPUT_DIR")
    input_zip, inventory_path, results_path, output_dir = map(Path, sys.argv[1:])
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    results = json.loads(results_path.read_text(encoding="utf-8"))
    result_by_match = {int(item["match_id"]): item for item in results}
    canonical_names = {item["archive_name"] for item in inventory}

    archives = {}
    with zipfile.ZipFile(input_zip) as package:
        for member in package.infolist():
            basename = Path(member.filename).name
            if basename in canonical_names:
                archives[basename] = json.loads(package.read(member))

    rows = []
    for item in inventory:
        result = result_by_match[int(item["match_id"])]
        if not result.get("eligible_v040_pre_match"):
            continue
        archive = archives[item["archive_name"]]
        analysis = archive["analysis"]
        decision = evaluate_v041(analysis)
        market = decision["market"]
        row = {
            "match_id": int(item["match_id"]),
            "date": result["result_kickoff_utc"][:10],
            "kickoff_utc": result["result_kickoff_utc"],
            "home_name": item["home_name"],
            "away_name": item["away_name"],
            "actual_score": result["actual_score"],
            "strongest_market": market,
            "strongest_probability_pct": decision["probability_pct"],
            "strongest_market_hit": bool(result[f"actual_{market}"]),
            "v040_decision": item["decision"],
            "v041_decision": decision["decision"],
            "direct_counter_market": decision["direct_counter_edge"]["counter_market"],
            "direct_counter_probability_pct": decision["direct_counter_edge"]["counter_probability_pct"],
            "direct_counter_difference_pp": decision["direct_counter_edge"]["difference_pp"],
            "direct_counter_edge_status": decision["direct_counter_edge"]["status"],
            "raw_sample_security": decision["sample_gate"]["raw_security"],
            "v041_sample_status": decision["sample_gate"]["status"],
            "failed_play_checks": ";".join(decision["failed_play_checks"]),
            "result_source_url": result["result_source_url"],
        }
        rows.append(row)

    play_v040 = [row for row in rows if row["v040_decision"] == "SPIELEN"]
    play_v041 = [row for row in rows if row["v041_decision"] == "SPIELEN"]
    summary = {
        "version": VERSION,
        "rule_frozen": True,
        "live_engine_modified": False,
        "clean_v040_pre_match_n": len(rows),
        "v040": {
            "decision_counts": dict(Counter(row["v040_decision"] for row in rows)),
            "spielen": rate(play_v040),
        },
        "v041": {
            "decision_counts": dict(Counter(row["v041_decision"] for row in rows)),
            "spielen": rate(play_v041),
            "spielen_by_market": grouped(play_v041, "strongest_market"),
            "spielen_by_date": grouped(play_v041, "date"),
            "spielen_candidates": play_v041,
        },
        "selection_integrity": {
            "outcome_fields_accepted_by_gate": False,
            "probability_core_changed": False,
            "odds_used": False,
            "external_match_data_used_by_gate": False,
        },
        "release_rule": "Nicht live einsetzen, bevor dieselbe eingefrorene Regel an chronologisch späteren Spielen bestätigt wurde.",
    }

    (output_dir / "v041_backtest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "v041_backtest_102.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "V041_OFFLINE_BACKTEST_REPORT.md").write_text(make_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
