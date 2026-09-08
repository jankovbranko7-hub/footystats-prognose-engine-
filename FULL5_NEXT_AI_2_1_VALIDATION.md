# FULL-5 NEXT AI 2.1 — Validation und Provenance

## Daten- und Split-Integrität

- Ausgangsbestand: 247 eindeutige Strict-Pre-Match- und resultverifizierte Matches.
- Development-Periode: chronologisch erste 160 Matches.
- Ranking-OOF innerhalb Development: 120 Matches; 720 Match×Markt-Zeilen.
- Abstention-Rolling-OOF: 60 Matches in zwei disjunkten späteren 30er-Blöcken.
- Frühere 87-Match-OOS-Periode: 0 verwendete Zeilen.
- Gruppierung erfolgt auf Match-Ebene; die sechs Märkte eines Spiels werden nie
  zwischen Train und Validation getrennt.

## Modellprovenance

- Ranking: eingefrorene Ridge-Logistic, `C=0.003`, 18 Inputs, 80 Bootstraps.
- Hash vor/nach Policy-Training:
  `73d070eaff41a676ac6be55e7496aa5e0f888d17e8517981414895e494c3c7f2`.
- Reliability: Ridge-Logistic, `C=0.001`; C durch minimalen chronologischen
  inneren Log Loss gelernt.
- Reliability-Inputs: 55 kontinuierliche/rohe Werte; keine Confirmations,
  Counter oder Robustheits-Booleans.
- Reliability-Bootstraps: 80.
- Aktionsgrenzen: 3-Cluster-KMeans auf trainierter Reliability; K=3 ist durch
  die Produktzustände vorgegeben, die Grenzwerte sind nicht manuell gesetzt.
- Observe: `0.6422845219898217`; Play: `0.6788983142117558`.

## Development-only Rolling OOF

| Zeitblock | Matches | Plays | Treffer | Trefferquote | Play Rate |
|---|---:|---:|---:|---:|---:|
| 0 | 30 | 13 | 8 | 61,54 % | 43,33 % |
| 1 | 30 | 16 | 10 | 62,50 % | 53,33 % |
| Gesamt | 60 | 29 | 18 | 62,07 % | 48,33 % |

Alle Zustände: 29 SPIELEN, 23 BEOBACHTEN, 8 KEIN BET. Play-Marktverteilung:
15 Over 2.5, 12 BTTS Yes, 1 Under 2.5, 1 Home Win. Reliability-Brier:
0,26245; Log Loss: 0,73994.

Diese Werte sind interne chronologisch gruppierte OOF-Validierung. Sie werden
nicht als unangetastetes OOS bezeichnet und ersetzen ausdrücklich nicht die
früheren AI-2.0-Policy-Zahlen.

## Finaler Decision-Pfad

Ranking → trainierte Reliability → gelernte Zustandsgrenzen. Confirmation,
Counter und manuelle Evidence-Schwellen sind nur UI-Diagnose. Nur
STRICT_PREMATCH, FIVE_FILES, AUDIT, LEAKAGE und REQUIRED_INPUTS dürfen die
AI-Aktion aus Integritätsgründen zu KEIN BET überschreiben.
