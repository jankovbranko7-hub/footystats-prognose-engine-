# FULL-7 Massensammler — Render Setup FINAL

Branch: `collector/full7-mass-17685`

## Status
- Produktionsbranch `main` bleibt unverändert.
- Produktionsservice `footystats-prognose-engine-` wird nicht für die Sammlung verwendet.
- Der Collector ist ein separater Render Background Worker.
- GitHub Smoke-Test prüft Python-Syntax, Manifest-Rekonstruktion, SHA-256, 17.685 Zeilen und 17.685 eindeutige match_id.
- Auto-Deploy des Workers ist AUS.
- Persistente Disk: Start mit 10 GB und Low-Disk-Guard bei 0,75 GB freiem Speicher.
- Bei Low-Disk beendet sich der Collector nach einem atomaren Checkpoint und kann nach Disk-Erweiterung exakt fortsetzen.

## Sicherheitsgrenzen
- `FOOTYSTATS_API_KEY` ausschließlich als Render Secret/Environment Variable eingeben.
- API-Key niemals in GitHub, Logdateien oder Chat kopieren.
- Keine Odds als Modellfeatures.
- ResultTarget bleibt getrennt.
- Fehlerhafte/unvollständige Matches werden quarantänisiert.
- Keine erfundenen Ersatzwerte.
- `strict_prematch=true` nur nach dem automatischen Strict-Validator.

## Verbindlicher Target-Lock
- Target-Spiele: 17.685
- Target-Spalten: `match_id,season_id`
- Raw Manifest SHA-256:
  `6f8d79f8bb477b8d7e1735a6e61a57e1f3ba998ca65af8aab903094bb64d5b65`
- Ursprüngliche vollständige Backtest-CSV SHA-256:
  `5cf612ad2d9d8cc94cda9098fafdd624cd1d7360003a7dc89f187e0b6623c00a`

Beim Workerstart rekonstruiert `bootstrap_input.py` das Target-Manifest aus den sieben GitHub-Teilen und bricht bei jeder Hash-/Anzahl-/Duplikatabweichung ab.

## Einmalige Render-Aktion
1. Render Dashboard öffnen.
2. **New -> Blueprint** wählen.
3. Repository `jankovbranko7-hub/footystats-prognose-engine-` auswählen.
4. Branch `collector/full7-mass-17685` auswählen.
5. Root-Datei `render.yaml` verwenden.
6. Render muss genau den Worker `full7-mass-collector-17685` anzeigen.
7. Bei `FOOTYSTATS_API_KEY` den Key direkt in Render als Secret eingeben.
8. Prüfen, dass eine persistente Disk `full7-mass-data` mit Mount `/var/data` und 10 GB angezeigt wird.
9. Blueprint erstellen/anwenden.

## Erwartete Startlogs
Zuerst:
- `MANIFEST_READY ... rows=17685 ...` oder `MANIFEST_OK ... rows=17685 ...`

Danach:
- `start total=17685 already_done=...`

Alle 10 verarbeiteten Spiele folgt ein Fortschrittsobjekt mit:
- processed
- strict_pass
- quarantined
- api_requests
- cache_hits
- unique_raw
- failed
- retry
- done_total
- disk_free_gb

Final darf nur erscheinen:
`FINISHED ... done 17685`

## Resume
State, Done-IDs, Matchpakete, Quarantäne und Raw-Cache liegen auf der persistenten Disk unter:
`/var/data/full7/output`

Nach Neustart/Re-Deploy werden fertige Matchpakete erneut erkannt. Bereits vollständig verarbeitete Spiele werden nicht erneut gesammelt.

## Low Disk
Wenn `disk_free_gb < 0.75`, beendet sich der Collector mit:
`DISK_LOW`

Dann:
1. Render-Disk vergrößern.
2. Worker erneut starten/deployen.
3. Collector setzt vom letzten vollständigen Checkpoint fort.

## Nach Abschluss
Noch NICHT automatisch kalibrieren.

Reihenfolge:
1. finaler Strict-/Quarantäne-Audit
2. Coverage/Missingness
3. Master-Feature-Tabelle
4. Feature-Audit
5. chronologisches Walk-Forward-Modell
6. OOS-Prognosen
7. Probability Calibration
8. neue SPIELEN-Gates
9. untouched Forward-Test
10. erst dann Produktionsentscheidung
