"""UI-only backtest report export for SPEC v1.1 / Engine v1.1.5.

The frozen analysis semantics are untouched. After a successful Render analysis,
the browser can export one JSON package containing the complete technical audit
response plus the exact five selected source files for later result-joined backtests.
"""
from __future__ import annotations
from typing import Any

from spec11_draw_parity_patch import apply_patch as apply_engine_patch

REPORT_EXPORT_MARKER = "SPEC_V1_1_ENGINE_V1_1_5_BACKTEST_REPORT"

_REPORT_UI = r'''
<style id="spec-backtest-report-style">
  #specBacktestDownloadWrap{margin:18px 0 8px 0;display:none}
  #specBacktestDownload{appearance:none;border:0;border-radius:12px;padding:13px 16px;font-weight:700;cursor:pointer;background:#2563eb;color:#fff;font-size:15px}
  #specBacktestDownload:disabled{opacity:.55;cursor:not-allowed}
  #specBacktestDownloadNote{margin-top:8px;font-size:13px;opacity:.78;line-height:1.35}
</style>
<div id="specBacktestDownloadWrap">
  <button id="specBacktestDownload" type="button">Backtest-Bericht herunterladen</button>
  <div id="specBacktestDownloadNote">Speichert vollständigen technischen Audit + die 5 ausgewählten FootyStats-JSON-Dateien in einem JSON-Paket.</div>
</div>
<script id="spec-backtest-report-script">
(function(){
  'use strict';
  const REPORT_MARKER = 'SPEC_V1_1_ENGINE_V1_1_5_BACKTEST_REPORT';
  let lastAudit = null;
  let lastFiles = [];

  function collectFilesFromBody(body){
    const out = [];
    try{
      if (body instanceof FormData){
        for (const pair of body.entries()){
          const value = pair[1];
          if (value instanceof File) out.push(value);
        }
      }
    }catch(_e){}
    return out;
  }

  function collectFilesFromInputs(){
    const out = [];
    try{
      document.querySelectorAll('input[type="file"]').forEach(function(input){
        if (input.files) Array.from(input.files).forEach(function(file){ out.push(file); });
      });
    }catch(_e){}
    return out;
  }

  function uniqueFiles(files){
    const seen = new Set();
    return files.filter(function(file){
      const key = [file.name, file.size, file.lastModified].join('|');
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function showDownloadButton(){
    const wrap = document.getElementById('specBacktestDownloadWrap');
    if (wrap) wrap.style.display = 'block';
  }

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async function(){
    const args = Array.from(arguments);
    const request = args[0];
    const url = typeof request === 'string' ? request : (request && request.url ? request.url : '');
    if (url.indexOf('/api/predict-bundle') !== -1){
      const bodyFiles = collectFilesFromBody(args[1] && args[1].body);
      lastFiles = uniqueFiles(bodyFiles.length ? bodyFiles : collectFilesFromInputs());
    }
    const response = await nativeFetch.apply(window, args);
    if (url.indexOf('/api/predict-bundle') !== -1){
      try{
        const clone = response.clone();
        clone.json().then(function(data){
          if (data && data.ok === true){
            lastAudit = data;
            if (!lastFiles.length) lastFiles = uniqueFiles(collectFilesFromInputs());
            showDownloadButton();
          }
        }).catch(function(){});
      }catch(_e){}
    }
    return response;
  };

  function safeName(value){
    return String(value || '')
      .normalize('NFKD')
      .replace(/[^A-Za-z0-9._-]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 70);
  }

  async function serializeInputFile(file){
    const text = await file.text();
    let parsed = null;
    let parseError = null;
    try{ parsed = JSON.parse(text); }
    catch(e){ parseError = String(e && e.message ? e.message : e); }
    return {
      name: file.name,
      size: file.size,
      last_modified_unix_ms: file.lastModified,
      json: parsed,
      parse_error: parseError,
      text_if_not_json: parsed === null ? text : null
    };
  }

  async function downloadReport(){
    if (!lastAudit) return;
    const button = document.getElementById('specBacktestDownload');
    if (button){ button.disabled = true; button.textContent = 'Bericht wird erstellt …'; }
    try{
      if (!lastFiles.length) lastFiles = uniqueFiles(collectFilesFromInputs());
      const inputs = [];
      for (const file of lastFiles) inputs.push(await serializeInputFile(file));
      const auditMatch = (lastAudit.audit && lastAudit.audit.match) || {};
      const pairing = lastAudit.pairing || {};
      const pkg = {
        export_schema: REPORT_MARKER,
        export_schema_version: '1.0',
        exported_at_utc: new Date().toISOString(),
        source_application: window.location.origin,
        spec_version: lastAudit.spec_version || '1.1',
        engine_version: lastAudit.engine_version || '1.1.5-draw-parity',
        match_id: pairing.match_id || auditMatch.match_id || null,
        home_name: auditMatch.home_name || null,
        away_name: auditMatch.away_name || null,
        kickoff_unix: pairing.kickoff_unix || auditMatch.kickoff_unix || null,
        expected_input_file_count: 5,
        embedded_input_file_count: inputs.length,
        input_files_complete: inputs.length === 5,
        input_files: inputs,
        technical_audit: lastAudit
      };
      const id = safeName(pkg.match_id || 'match');
      const home = safeName(pkg.home_name || 'home');
      const away = safeName(pkg.away_name || 'away');
      const filename = [id, home, away, 'SPEC-v1.1_ENGINE-v1.1.5_BACKTEST.json'].filter(Boolean).join('_');
      const blob = new Blob([JSON.stringify(pkg, null, 2)], {type:'application/json;charset=utf-8'});
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function(){ URL.revokeObjectURL(href); }, 2000);
    } finally {
      if (button){ button.disabled = false; button.textContent = 'Backtest-Bericht herunterladen'; }
    }
  }

  function mountButton(){
    const wrap = document.getElementById('specBacktestDownloadWrap');
    const button = document.getElementById('specBacktestDownload');
    if (!wrap || !button) return;
    button.addEventListener('click', downloadReport);
    const main = document.querySelector('main');
    const form = document.querySelector('form');
    if (form && form.parentNode) form.parentNode.insertBefore(wrap, form.nextSibling);
    else if (main) main.appendChild(wrap);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountButton);
  else mountButton();
})();
</script>
'''


def apply_patch(legacy: Any) -> Any:
    app = apply_engine_patch(legacy)
    if REPORT_EXPORT_MARKER not in legacy.INDEX_HTML:
        if "</body>" in legacy.INDEX_HTML:
            legacy.INDEX_HTML = legacy.INDEX_HTML.replace("</body>", _REPORT_UI + "\n</body>")
        else:
            legacy.INDEX_HTML += _REPORT_UI
    return app
