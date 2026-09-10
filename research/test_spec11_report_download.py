"""Regression checks for the SPEC v1.1 / Engine v1.1.5 backtest-report export UI."""
import app
import app_v040 as legacy

html = legacy.INDEX_HTML
assert app.app.version == '1.1.5-draw-parity'
assert 'SPEC_V1_1_ENGINE_V1_1_5_BACKTEST_REPORT' in html
assert 'Backtest-Bericht herunterladen' in html
assert 'vollständigen technischen Audit + die 5 ausgewählten FootyStats-JSON-Dateien' in html
assert '/api/predict-bundle' in html
assert 'expected_input_file_count: 5' in html
assert 'input_files_complete: inputs.length === 5' in html
assert 'technical_audit: lastAudit' in html
print('SPEC v1.1 / Engine v1.1.5 backtest report download UI OK')
