"""Regression tests for SPEC v1.1 cross-market normalization."""
from __future__ import annotations

import spec11_cross_market_normalization_patch as patch
from spec11_native_engine import SUPPORT, CONTRADICT


def _sig(source: str, status: str, market: str):
    return {
        "source": source,
        "domain": f"TEST_{source}_{status}",
        "market": market,
        "status": status,
        "reason": "cross-market regression",
        "ranking_eligible": True,
    }


def test_perfect_three_of_three_beats_four_of_five_with_one_contra():
    # O/U shape: all three applicable central sources support, none contradict.
    ou = []
    ou += [_sig("MATCH", SUPPORT, "over_2_5") for _ in range(4)]
    ou += [_sig("LEAGUE", SUPPORT, "over_2_5") for _ in range(7)]
    ou += [_sig("FORM", SUPPORT, "over_2_5") for _ in range(6)]
    ou_row = patch._normalized_aggregate(ou, "over_2_5")

    # 1X2 shape matching the observed structural problem:
    # MATCH 2:0, LEAGUE 2:0, FORM 1:2, TABLE 1:0, PLAYER 2:0.
    one_x_two = []
    one_x_two += [_sig("MATCH", SUPPORT, "home_win") for _ in range(2)]
    one_x_two += [_sig("LEAGUE", SUPPORT, "home_win") for _ in range(2)]
    one_x_two += [_sig("FORM", SUPPORT, "home_win")]
    one_x_two += [_sig("FORM", CONTRADICT, "home_win") for _ in range(2)]
    one_x_two += [_sig("TABLE", SUPPORT, "home_win")]
    one_x_two += [_sig("PLAYER", SUPPORT, "home_win") for _ in range(2)]
    x_row = patch._normalized_aggregate(one_x_two, "home_win")

    assert ou_row["source_net_evidence"] == 3
    assert x_row["source_net_evidence"] == 3

    assert ou_row["applicable_central_source_count"] == 3
    assert x_row["applicable_central_source_count"] == 5

    assert ou_row["source_balance"] == 1.0
    assert x_row["source_balance"] == 0.6
    assert ou_row["source_contradiction_rate"] == 0.0
    assert x_row["source_contradiction_rate"] == 0.2

    # The correction: perfect 3/3 must rank above 4/5 with one opposing source.
    assert patch._normalized_rank_key(ou_row) > patch._normalized_rank_key(x_row)


def main():
    test_perfect_three_of_three_beats_four_of_five_with_one_contra()
    print("SPEC v1.1 cross-market normalization regression OK")


if __name__ == "__main__":
    main()
