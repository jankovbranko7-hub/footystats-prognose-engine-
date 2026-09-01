# V0.5.0 SHADOW — erster Forschungs-Lauf

Status: **NON-PRODUCTION / NICHT DEPLOYEN**

Basis: ursprünglicher V0.4.0-Commit `06d5f63254622c2dba21f72a3e64ff3d356eb2f6`.
Produktivsystem, Render und iPhone-V2-Kurzbefehl bleiben unverändert.

## Datensatz

- ZIP-Archive gesamt: 153
- V0.4.0-Archive: 131
- eindeutige V0.4.0-Matches: 123
- saubere Pre-Match-Auswahl: mindestens 5 Minuten vor Anpfiff
- nach Dublettenbereinigung: **101 eindeutige V0.4.0-Pre-Match-Spiele**

Für Dubletten wurde die früheste zulässige Pre-Match-Analyse verwendet.

## Shadow-Änderungen

1. **Family-relative Edge** statt Abstand zu einem fachlich unabhängigen zweiten Markt.
   - BTTS Yes wird gegen BTTS No geprüft.
   - Over 2,5 wird gegen Under 2,5 geprüft.
   - Sieg Heim/Auswärts wird gegen die stärkste echte 1X2-Alternative einschließlich Draw geprüft.

2. **Kontrollierte Formkorrektur** der V0.4-liga-relativen Lambdas.
   - Last-5-xG/xGA gegen längeres Formfenster.
   - Wirkung auf Lambda auf maximal +/-10 % begrenzt.
   - Shots-on-Target wird als Agreement-Check verwendet.
   - Tore-vs-xG wird als Regression-Diagnose ausgewiesen, nicht blind doppelt gewichtet.

3. **Sensitivity Band** statt falscher Sicherheit.
   - Deterministischer Stressbereich, ausdrücklich kein kalibriertes Konfidenzintervall.

4. **Parallele Schwellen-Szenarien** 60 / 62 / 65 / 67 %.
   - Keine Schwelle wird durch diesen In-Sample-Test zur Produktionsregel erklärt.

## Erster Lauf auf Clean-101

- analysiert: **101**
- stärkster Markt gegenüber V0.4.0 geändert: **8**
- Family Edge = KLAR: **98 / 101**
- starke Cross-Family-Bestätigung (BTTS Yes + Over 2,5 bzw. BTTS No + Under 2,5, beide >=60 %): **34 / 101**
- mittlere absolute Formkorrektur Heim-Lambda: **1,47 %**
- mittlere absolute Formkorrektur Auswärts-Lambda: **1,82 %**

### Populationen nur nach Shadow-Wahrscheinlichkeit + Family Edge

- >=60 %: **45** Spiele
- >=62 %: **30** Spiele
- >=65 %: **15** Spiele
- >=67 %: **6** Spiele

### Sehr konservative Shadow-Kandidaten mit V0.4-Removal-Proxy

- Schwelle 60 %: **1**
- Schwelle 62 %: **1**
- Schwelle 65 %: **0**
- Schwelle 67 %: **0**

Der starke Rückgang ist erwartbar: Der erste Shadow-Lauf übernimmt den alten V0.4-Removal-Test nur als Proxy, sofern derselbe Top-Markt erhalten bleibt. Das ist bewusst konservativ und noch **kein** neuer V0.5-Removal-Test.

## Interpretation

Diese Zahlen bewerten noch **nicht die Trefferquote** der V0.5-Variante. Sie zeigen zunächst, wie stark sich die Modellentscheidungen durch die Forschungsänderungen verschieben. Die tatsächliche Güte muss gegen echte Endstände und anschließend auf neuen, bisher ungesehenen Spielen geprüft werden.

Die bisherigen 101 Spiele sind Entwicklungs-/Hypothesendaten. Änderungen dürfen nicht allein auf diesem Sample optimiert und anschließend als validiert bezeichnet werden.

## Freigaberegel

V0.5 darf V0.4 produktiv nur ersetzen, wenn ein eingefrorener Shadow-Stand auf neuen Out-of-Sample-Spielen mindestens gleich gute oder bessere Kalibrierung/Trennschärfe zeigt und keine wesentliche Marktgruppe verschlechtert.
