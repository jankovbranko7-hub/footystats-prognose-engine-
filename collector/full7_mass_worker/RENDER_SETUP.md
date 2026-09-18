# FULL-7 Massensammler — Render Setup

Branch: `collector/full7-mass-17685`

## Sicherheitsgrenzen
- Produktionsbranch `main` nicht ändern.
- Produktionsservice `footystats-prognose-engine-` nicht für die Sammlung verwenden.
- `FOOTYSTATS_API_KEY` ausschließlich als Render Secret/Environment Variable eingeben.
- Der Worker schreibt nur auf seine persistente Disk unter `/var/data`.

## Einmalige Render-Aktion
1. Render Dashboard öffnen.
2. **New -> Blueprint** wählen.
3. Repository `jankovbranko7-hub/footystats-prognose-engine-` wählen.
4. Branch `collector/full7-mass-17685` verwenden.
5. Root-`render.yaml` erkennen lassen.
6. Render zeigt den Worker `full7-mass-collector-17685` mit persistenter Disk.
7. Bei `FOOTYSTATS_API_KEY` den FootyStats-Key direkt in Render eintragen.
8. Blueprint anwenden / Service erstellen.

## Erwarteter Startablauf
Zuerst wird der Target-Bootstrap ausgeführt:
- 100 Season-Sets werden über `league-matches` rekonstruiert.
- Pro Season müssen Anzahl, Match-ID-SHA256, Resultat-SHA256 und vollständiger Identity-SHA256 exakt dem Original-Workbook-Manifest entsprechen.
- Bei irgendeiner Abweichung: **ABORT**, keine Massensammlung.

Erwartete Logs:
- `BOOTSTRAP 1/100 ... VERIFIED`
- ...
- `BOOTSTRAP 100/100 ... VERIFIED`
- `BOOTSTRAP FINISHED rows=17685 ...`
- danach `start total=17685 ...`

## Collector
Danach:
- Strict cutoff = Kickoff - 1 Sekunde
- Collector + Strict-Validator + SHA-Raw-Cache
- Checkpoint nach jedem Match
- Fehlerhafte/unvollständige Matches -> Quarantäne
- keine erfundenen Ersatzwerte
- `FINISHED` nur wenn `done == processed == 17685`

## Persistent
`FULL7_ROOT=/var/data/full7/output`

Enthält u. a.:
- `state.json`
- `done_ids.txt`
- `progress.jsonl`
- `matches/`
- `quarantine/`
- `raw_cache/`
- `raw_cache_index.jsonl`
- `bootstrap_target_audit.json`
- `bootstrap_target_verified.json`

## Neustart
Bei Render-Neustart:
- bereits verifizierter Target-Input wird per SHA geprüft und wiederverwendet
- fertige Matches werden aus `done_ids.txt` + vollständigen Matchordnern rekonstruiert
- Sammlung setzt fort statt von vorn zu beginnen

## Nach Abschluss
Noch keine Kalibrierung im Worker.
Erst Export/Audit der vollständigen Sammlung, danach Feature-Audit -> Walk-Forward -> Kalibrierung.
