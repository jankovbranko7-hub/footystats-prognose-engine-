"""Smoke tests for SPEC v1.1 full-signal strongest-market analysis."""
from research.test_spec11_native_engine import build_bundle
from spec11_strongest_market_engine import analyze_bundle


def main():
    result = analyze_bundle(build_bundle(0, 1))
    assert result["ok"] is True, result
    assert result["analysis_type"] == "SPEC_V1_1_STRONGEST_MARKET"
    assert result["engine_version"] == "1.1.2-full-signal-breadth"
    assert result["sample_state"]["home"]["class"] == "COLD START"
    assert result["sample_state"]["away"]["class"] == "LOW SAMPLE"
    assert result["method"]["architecture"] == "SPEC_V1_1_FULL_SIGNAL_COMPARISON"
    assert result["method"]["decision_engine"] == "NONE"
    assert result["method"]["probability_core"] == "NONE"
    assert result["method"]["v043_used"] is False
    assert result["method"]["v042_used"] is False
    assert result["method"]["fallback"] == "NONE"
    assert "Nur HOME_ID/AWAY_ID" in result["method"]["player_analysis_scope"]
    assert len(result["markets"]) == 7
    assert "strongest_market" in result
    assert "action" not in result["strongest_market"]
    assert all("action" not in market for market in result["markets"])
    assert all("source_evidence" in market for market in result["markets"])
    assert all("source_net_evidence" in market for market in result["markets"])
    domains = set(result["data_coverage"]["signal_domains"])
    assert "OVER_UNDER_LADDER" in domains
    assert "RESULT_FORM_TREND" in domains
    assert "GOAL_DIFFERENCE_PER_MATCH" in domains
    assert "PLAYER_CONCENTRATION" in domains
    assert result["data_coverage"]["signal_domain_count"] >= 20
    assert result["recommendation"] in {m["label"] for m in result["markets"]} | {"KEINE KLARE EMPFEHLUNG"}
    bad = build_bundle(0, 1)[:-1]
    result_bad = analyze_bundle(bad)
    assert result_bad["ok"] is False and result_bad["phase"] == "SPEC11_FILE_PAIRING_FAILED"
    print("SPEC v1.1 full-signal strongest-market smoke OK", result["recommendation"], result["data_coverage"]["signal_domain_count"])


if __name__ == "__main__":
    main()
