# FULL-7 V3 Massensammler 1.1

Collector + Strict-Validator + persistentem SHA-256-Raw-Cache. Keine Kalibrierung, kein Modelltraining.

- Checkpoint nach jedem Match.
- State-Reconciliation beim Neustart.
- FINISHED nur wenn done == total == processed.
- Standard: 17.685 Inputspiele.
- Raw-Cache prüft SHA-256 beim Lesen.
- Vollständige Home/Away-Teamobjekte und Playerobjekte bleiben für den späteren Feature-Audit erhalten.

Render-Worker:
- FOOTYSTATS_API_KEY als Secret setzen.
- FULL7_ROOT zeigt auf die persistente Disk.
- FULL7_CSV zeigt auf die auf Disk rekonstruierte 17.685-Spiele-CSV.
