"""Regression checks for the SPEC v1.1 / Engine v1.1.6 backtest-report export UI."""
import app
import app_v040 as legacy

html = legacy.INDEX_HTML
assert app.app.version == '1.1.6-cross-market-normalized'
assert 'SPEC_V1_1_ENGINE_V1_1_6_BACKTEST_REPORT' in html
assert 'Backtest-Bericht herunterladen' in html
assert 'vollständigen technischen Audit + die 5 ausgewählten FootyStats-JSON-Dateien' in html
assert '/api/predict-bundle' in html
assert 'expected_input_file_count: 5' in html
assert 'input_files_complete: inputs.length === 5' in html
assert 'technical_audit: lastAudit' in html
assert 'available_central_sources' in html
assert "+'/'+esc((topMarket.available_central_sources||[]).length)+' aktiv" in html
assert "central_support_sources||[]).length)+'/5</div>" not in html
print('SPEC v1.1 / Engine v1.1.6 backtest report download UI OK')
