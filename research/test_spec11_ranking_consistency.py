"""Regression tests for SPEC v1.1 strongest-market ranking consistency."""
from __future__ import annotations

import spec11_strongest_market_engine as engine
import spec11_target_player_scope_patch as patch
from spec11_native_engine import SUPPORT, CONTRADICT, NEUTRAL


def _sig(source: str, status: str, market: str = "under_2_5"):
    return {
        "source": source,
        "domain": f"TEST_{source}_{status}",
        "market": market,
        "status": status,
        "reason": "regression",
        "ranking_eligible": True,
    }


def test_negative_total_cannot_be_clear():
    # Mirrors the Fenerbahce-Roma audit shape:
    # MATCH 3:0, LEAGUE 1:0, FORM 1:6 + one neutral => source direction +1,
    # but total evidence 5:6 => -1. This must never be CLEAR.
    signals = []
    signals += [_sig("MATCH", SUPPORT) for _ in range(3)]
    signals += [_sig("LEAGUE", SUPPORT)]
    signals += [_sig("FORM", SUPPORT)]
    signals += [_sig("FORM", CONTRADICT) for _ in range(6)]
    signals += [_sig("FORM", NEUTRAL)]
    row = patch._consistent_aggregate(signals, "under_2_5")
    assert row["net_evidence"] == -1
    assert row["source_net_evidence"] == 1
    assert row["source_evidence"]["FORM"]["block_balance"] == -0.625
    assert row["source_evidence"]["MATCH"]["block_balance"] == 1.0
    assert row["source_evidence"]["LEAGUE"]["block_balance"] == 1.0
    assert row["direction_conflict"] is True
    clear, reason = patch._clear_market(row, None)
    assert clear is False
    assert reason == "SOURCE_AND_TOTAL_EVIDENCE_CONFLICT"


def test_positive_consistent_market_can_be_clear():
    signals = [
        _sig("MATCH", SUPPORT),
        _sig("MATCH", SUPPORT),
        _sig("LEAGUE", SUPPORT),
        _sig("FORM", NEUTRAL),
    ]
    row = patch._consistent_aggregate(signals, "under_2_5")
    assert row["net_evidence"] == 3
    assert row["source_net_evidence"] == 2
    assert row["direction_conflict"] is False
    clear, reason = patch._clear_market(row, None)
    assert clear is True
    assert reason == "CLEAR_POSITIVE_CONSISTENT"


def main():
    test_negative_total_cannot_be_clear()
    test_positive_consistent_market_can_be_clear()
    print("SPEC v1.1 ranking consistency regression OK")


if __name__ == "__main__":
    main()
