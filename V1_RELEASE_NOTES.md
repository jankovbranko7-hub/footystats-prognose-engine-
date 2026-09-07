# FootyStats V1 — vollständige Multi-Market Production Engine

## Produktionskern bleibt eingefroren

V1 baut direkt auf dem bestehenden V0.4.3 FULL-5 Probability Core auf und ersetzt ihn nicht.

Verbindlich aktiv:

- 40 bestehende FULL-5 Features
- V0.4.2 Hybrid-Lambda als Basis/Fallback
- Dixon-Coles mit rho = -0.25
- Elite-Lambda-Korrektur deaktiviert
- keine erfundenen Ersatzwerte
- weiterhin exakt fünf FootyStats-Dateien: MatchDaten, LeagueDaten, FormDaten, TableDaten, PlayerDaten

### Alpha-Prüfung

`v043_engine.py` enthält als Modul-Default weiterhin `FULL5_ALPHA = 1.0`. Der produktive Release-Layer `v043_release.py` setzt jedoch bewusst `FULL5_ALPHA = 3.0`, überschreibt damit den Engine-Wert und lädt die dazugehörigen auf 137 Strict-Prematch-Archiven refitteten Produktionsparameter. Der V1-Health-Contract prüft deshalb explizit `alpha = 3.0`.

Der V0.4.3-Core wird durch V1 nicht editiert.

### Finaler Produktionsaudit

Vor der endgültigen Freigabe wurden zwei Integrationsfehler im Full-Specialist-Entwurf gefunden und im Produktions-Lock `v1_release.py` korrigiert:

1. **FormDaten-Routing:** Der reale bestehende fünf-Dateien-Export speichert Form-Seiten unter `teams`. Der erste Full-Specialist-Entwurf suchte zusätzlich nur unter `pages`/`data`; dadurch wäre das neue Form Regime bei realen Exporten teilweise leer geblieben. Produktion liest jetzt verbindlich `teams` und behält `pages`/`data` nur als kompatible alternative Struktur bei. Es werden keine Ersatzwerte erzeugt.
2. **Robuste Cross-Family-Auswahl:** Zwischen 1X2, BTTS und O/U wird nicht zuerst nach roher Probability sortiert. Die Auswahl verwendet zuerst die bereits etablierte normalisierte Marktfamilienstärke und danach erst die Probability. Dadurch wird 1X2 gegenüber binären Märkten nicht strukturell benachteiligt.

Diese Korrekturen verändern weder Lambda noch FULL-5-Parameter, Dixon-Coles oder die sechs Markt-Wahrscheinlichkeiten.

## Gate V1

Die strukturelle Confirmation-Regel lautet:

`required = min(original_required, structural_applicable_block_count_for_family)`

Strukturelle Maxima:

- 1X2: 4 — UNDERLYING + MATCH + FORM + TABLE
- BTTS: 3 — UNDERLYING + MATCH + FORM
- O/U 2.5: 4 — UNDERLYING + MATCH + FORM + PLAYER

Damit kann Low-Sample-BTTS erstmals mit 3/3 SPIELEN erreichen. 2/3 bleibt blockiert. Fehlende Daten reduzieren die strukturelle Anforderung nicht.

## Alle sechs Märkte werden separat geprüft

V1 erstellt für jedes Spiel eine eigene Gate-Bewertung für:

1. HOME WIN
2. AWAY WIN
3. BTTS YES
4. BTTS NO
5. OVER 2.5
6. UNDER 2.5

Jede Bewertung enthält Probability, normalisierte Marktfamilienstärke, klassische Confirmations, Counter-Blöcke, Gate-V1-Anforderung, Specialist-Alignment und konkrete Gründe.

Der rohe V0.4.3-Core-Topmarkt bleibt als `core_strongest_market` sichtbar. Zusätzlich wählt V1 den stärksten robust freigegebenen Markt als `selected_robust_market`. Zuerst zählt die Freigabeklasse SPIELEN/BEOBACHTEN/AUSLASSEN, innerhalb derselben Klasse die normalisierte Marktfamilienstärke und erst danach die rohe Probability. Dadurch kann ein geringfügig niedrigerer, aber relativ stärkerer und strukturell freigegebener Markt vor einem höheren Roh-Prozentmarkt gewählt werden, ohne dessen Probability zu verändern.

## Vollständig aktive V1-Specialists

### BTTS Specialist

Aktiviert:

- bestehendes First-Half-BTTS Venue Profile
- CS/FTS Scoring-Survival
- Second-Half-BTTS Venue Profile
- Form-BTTS-Regime
- Player Depth / Concentration als Reliability-Kontext

### Over/Under 2.5 Specialist

Aktiviert:

- Shot Conversion
- Shots per Goal
- SOT per Goal
- First-Half Goal Intensity
- Second-Half Goal Intensity
- FTS / Scoring Failure
- Form Tempo

Finishing-Metriken werden als eine korrelierte Evidenzgruppe behandelt und nicht mehrfach als unabhängige Confirmations gezählt.

### 1X2 Specialist

Aktiviert:

- Home/Away PPG relativ zur jeweiligen Liga-Baseline
- relative Venue-xG/xGA Attack/Defence Strength
- normalisierte Tabellenposition `(Position - 1) / (Teams - 1)`
- Venue-vs-Overall-Differenz
- aktuelle Form
- Player-Depth- und Sample-Reliability-Kontext

### Player Structure

Zusätzlich ausgewiesen werden unter anderem:

- Players found / Spieler mit Minuten
- Appearances und Minuten overall/home/away
- Goals involved per 90
- Goals per 90 home/away
- Top-3- und Top-5-Goal Share
- Top-3-Contribution Share
- Produktion außerhalb Top 3
- Minutenkonzentration
- Venue Player Production

Player Structure ist Reliability/Fragility, kein automatischer Lambda-Zuschlag.

### Form Regime

Form wird als eine Datenfamilie strukturiert:

- FORM_ATTACK
- FORM_DEFENCE
- FORM_BTTS
- FORM_TEMPO

Last5/Last6/Last10 werden nie als drei unabhängige Confirmations gezählt. Der Produktions-Lock liest dabei den realen `teams`-Container des bestehenden FormDaten-Exports.

### H2H Diagnostics

H2H wird nur aus MatchDaten gelesen und bleibt ein kleiner Diagnostic-/Counterargument-Kontext. Es erhält kein eigenständiges Gate-Gewicht und keine Lambda-Wirkung.

## Leakage Guard

V1-Specialists und Gates ignorieren Zielspiel-Live-/Post-Kickoff-Felder, darunter Goal Counts, Zielspiel-xG, Shots, SOT, Corners, Cards, Possession sowie `gpt_en`.

Pre-Match-Felder wie `team_a_xg_prematch`, `team_b_xg_prematch` und Pre-Match-PPG bleiben erlaubt.

## Double-Counting Guard

V1 trennt explizit:

- CORE EVIDENCE
- SPECIALIST EVIDENCE
- INDEPENDENT CONFIRMATION
- DIAGNOSTIC

Specialists erhöhen niemals künstlich den klassischen Confirmation Count. Ein Specialist darf bei klarer, unopponierter Mehrsignal-Widerspruchslage eine SPIELEN-Freigabe auf BEOBACHTEN begrenzen; die zugrunde liegende V0.4.3-Probability bleibt unverändert.

## Render-UI

Weiter sichtbar:

- Spielpaarung
- Match-ID
- FULL-5 AKTIV / FALLBACK
- Core-Topmarkt
- Probability
- finale Entscheidung
- Warum BEOBACHTEN?

Neu sichtbar:

- V1 robuste Wahl
- BTTS Specialist
- O/U Specialist
- 1X2 Specialist
- Player Structure
- Leakage-/Double-Counting-Status
- alle sechs Märkte mit Probability, Entscheidung und Confirmation-Stand

## Backup / Rollback

Das vorhandene Backup `backup/v0.4.3-full5-2026-09-07` bleibt unverändert. V1 wird ausschließlich als Overlay auf dem bestehenden Produktionspfad aufgebaut.

## Tests

CI prüft mindestens:

- 40 FULL-5 Features unverändert
- Alpha 3.0 im Produktionspfad
- Dixon-Coles rho = -0.25
- keine V1-Probability-Reweighting-Logik
- kein neuer Lambda-Core
- Gate V1 BTTS 3/3 vs. 2/3
- strukturelle 1X2/O-U Requirements
- alle sechs Märkte vorhanden
- realer `teams`-Container aus FormDaten wird gelesen
- robuste Cross-Family-Auswahl nutzt normalisierte Family Strength vor Roh-Probability
- Leakage Guard
- Double-Counting Guard
- alle Specialists aktiv
- Spielpaarung und konkrete BEOBACHTEN-Begründung sichtbar
- V0.4.3-Core-Dateien im Feature-Diff unverändert

V1.0 ist damit kein Challenger-Stufenmodell mehr, sondern der vollständige gemeinsame Produktionszustand der beschriebenen V1-Komponenten.
