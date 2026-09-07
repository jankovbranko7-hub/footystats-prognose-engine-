"""FootyStats V1 final production lock.

This module wires the full V1 specialist layer onto the frozen V0.4.3 FULL-5
probability core and applies production fixes found during final audits:

1. FormDaten from the existing iPhone exporter stores form pages under
   ``teams``. The initial full-specialist draft also looked for ``pages`` and
   would therefore miss real FormDaten in production. This lock accepts the
   real ``teams`` shape while retaining compatibility with ``pages``/``data``.
2. Cross-family robust-market selection must use the same normalized family
   strength logic already established by the V0.4.3/V0.4.1 family selector.
   Comparing raw percentages first would structurally disadvantage 1X2 versus
   binary BTTS/O-U markets.
3. The Render UI exposes an exact decision rationale not only for BEOBACHTEN,
   but also for SPIELEN and AUSLASSEN. This is presentation-only and reads the
   already computed V1 decision reasons/gates.

No lambda, FULL-5 coefficient, Dixon-Coles parameter or market probability is
changed here.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import v1_full_engine as engine

VERSION = engine.VERSION
BASELINE = engine.BASELINE


def _form_records_production(form_data: Any) -> List[Dict[str, Any]]:
    """Read the real five-file FormDaten export without inventing fallback data."""
    records: List[Dict[str, Any]] = []
    if not isinstance(form_data, dict):
        return records

    containers = []
    teams = form_data.get("teams")
    if isinstance(teams, list):
        containers.extend(teams)
    pages = form_data.get("pages")
    if isinstance(pages, list):
        containers.extend(pages)

    for page in containers:
        if isinstance(page, dict):
            data = page.get("data")
            if isinstance(data, list):
                records.extend(item for item in data if isinstance(item, dict))

    if not records:
        data = form_data.get("data")
        if isinstance(data, list):
            records.extend(item for item in data if isinstance(item, dict))
    return records


def _num_obj(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _select_robust_market_production(
    assessments: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Prefer decision quality, then normalized family strength, then probability."""
    if not assessments:
        return None
    for decision in ("SPIELEN", "BEOBACHTEN", "AUSLASSEN"):
        candidates = [item for item in assessments if item.get("decision") == decision]
        if candidates:
            return max(
                candidates,
                key=lambda item: (
                    _num_obj(item.get("family_strength_pct")) or -1.0,
                    _num_obj(item.get("probability_pct")) or -1.0,
                ),
            )
    return None


def _install_exact_decision_ui(legacy: Any) -> None:
    """Show the exact final rationale for SPIELEN and AUSLASSEN in Render."""
    html = legacy.INDEX_HTML

    js_anchor = "    const v1Double=((v1Specs.double_counting_guard||{}).status)||'—';\n"
    if js_anchor not in html:
        raise RuntimeError("V1 exact-decision JS anchor not found.")

    js_extra = r"""    const v1SelectedAssessment=v1Markets.find(function(m){return m&&m.key===v1Selected.key;})||{};
    const exactDecisionVisible=(finalDecision==='SPIELEN'||finalDecision==='AUSLASSEN');
    const exactDecisionTitle=finalDecision==='SPIELEN'?'Warum SPIELEN?':'Warum AUSLASSEN?';
    const exactDecisionLabel=v1Selected.label||strongest.label||'Der ausgewählte Markt';
    const exactDecisionProbability=(v1Selected.probability_pct!=null?v1Selected.probability_pct:strongest.probability_pct);
    const exactDecisionLead=finalDecision==='SPIELEN'
      ? exactDecisionLabel+(exactDecisionProbability!=null?' bei '+exactDecisionProbability+' %':'')+' wurde nach Gate V1 freigegeben.'
      : exactDecisionLabel+(exactDecisionProbability!=null?' bei '+exactDecisionProbability+' %':'')+' wird trotz des Modellsignals nicht freigegeben.';
    const exactDecisionReason=decisionReasons.length
      ? decisionReasons[0]
      : (finalDecision==='SPIELEN'?'Alle erforderlichen Freigabe-Gates sind bestanden.':'Mindestens ein hartes Gate verhindert die Freigabe.');
    const exactDecisionExtras=decisionReasons.slice(1);
    const exactConfirming=Array.isArray(v1SelectedAssessment.confirming_block_labels)
      ? v1SelectedAssessment.confirming_block_labels.filter(Boolean)
      : (Array.isArray(v1SelectedAssessment.confirming_blocks)?v1SelectedAssessment.confirming_blocks.filter(Boolean):[]);
    const exactCounters=Array.isArray(v1SelectedAssessment.counter_block_labels)
      ? v1SelectedAssessment.counter_block_labels.filter(Boolean)
      : (Array.isArray(v1SelectedAssessment.counter_blocks)?v1SelectedAssessment.counter_blocks.filter(Boolean):[]);
    const exactRequired=v1SelectedAssessment.required_confirmations;
    const exactStrength=v1SelectedAssessment.family_strength_pct;
    const exactGates=protocol.gates||{};
    const exactPre=(exactGates.pre_match_integrity||data.pre_match_integrity||{});
    const exactRobust=(exactGates.robustness||((data.diagnostics||{}).robustness_status)||'—');
    const exactQuality=(exactGates.data_quality||((data.diagnostics||{}).data_quality)||'—');
    const exactSample=((data.samples||{}).security)||((data.diagnostics||{}).sample_security)||'—';
    const exactAlignment=v1SelectedAssessment.specialist_alignment||{};
    const exactSpecialist=exactAlignment.clear_support?'STÜTZT'
      :(exactAlignment.clear_contradiction?'WIDERSPRICHT':((exactAlignment.specialist_direction&&exactAlignment.specialist_direction!=='NICHT BEWERTBAR')?exactAlignment.specialist_direction:'NEUTRAL / NICHT BEWERTBAR'));
    const exactGateParts=[];
    if(exactRequired!=null)exactGateParts.push('Bestätigungen '+exactConfirming.length+'/'+exactRequired);
    exactGateParts.push('Gegenargumente '+(exactCounters.length?exactCounters.join(', '):'keine'));
    if(exactStrength!=null)exactGateParts.push('Marktfamilienstärke '+exactStrength+' %');
    if(exactRobust)exactGateParts.push('Robustheit '+exactRobust);
    if(exactQuality)exactGateParts.push('Datenqualität '+exactQuality);
    if(exactSample)exactGateParts.push('Stichprobe '+exactSample);
    if(exactPre.status)exactGateParts.push('Pre-Match '+exactPre.status);
    exactGateParts.push('Specialist '+exactSpecialist);
    let exactTiming='';
    if(finalDecision==='AUSLASSEN'&&exactPre.strict_pre_match===false&&exactPre.minutes_to_kickoff!=null){
      const after=Math.abs(Number(exactPre.minutes_to_kickoff));
      if(Number.isFinite(after)){
        const hours=Math.floor(after/60);
        const mins=Math.round(after-hours*60);
        exactTiming='Zeitprüfung: Analyse '+hours+' h '+mins+' min nach dem in den FootyStats-Daten gespeicherten Kickoff.';
      }
    }
    const exactExtraHtml=exactDecisionExtras.map(function(r){return '<div class="s">• '+escapeHtml(r)+'</div>';}).join('');
    const exactDecisionCard=exactDecisionVisible
      ? '<div class="c"><h3>'+escapeHtml(exactDecisionTitle)+'</h3>'+ 
        '<div class="b">'+escapeHtml(exactDecisionLead)+'</div>'+ 
        '<div class="s" style="margin-top:12px">Entscheidender Grund</div>'+ 
        '<p>'+escapeHtml(exactDecisionReason)+'</p>'+exactExtraHtml+
        (exactTiming?'<p>'+escapeHtml(exactTiming)+'</p>':'')+
        '<div class="s" style="margin-top:12px">Gate-Bild: '+escapeHtml(exactGateParts.join(' · '))+'</div>'+ 
        (exactConfirming.length?'<div class="s">Bestätigend: '+escapeHtml(exactConfirming.join(', '))+'</div>':'')+
        '</div>'
      : '';
"""
    html = html.replace(js_anchor, js_anchor + js_extra, 1)

    card_anchor = "      observeCard+\n"
    if card_anchor not in html:
        raise RuntimeError("V1 exact-decision card anchor not found.")
    legacy.INDEX_HTML = html.replace(card_anchor, "      exactDecisionCard+\n" + card_anchor, 1)


# Install the audited production fixes before the full engine is applied.
engine._form_records = _form_records_production
engine._select_robust_market = _select_robust_market_production


def apply_patch(legacy: Any) -> Any:
    """Install final V1 while keeping the entire V0.4.3 probability path frozen."""
    app = engine.apply_patch(legacy)
    _install_exact_decision_ui(legacy)
    return app
