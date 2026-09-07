import ast
import inspect
import time
import unittest

import app_v1
import v1_standalone_engine as v1
from v1_runtime_contract import FORBIDDEN_RUNTIME_MODULES


def team(tid, home_xg=1.8, away_xg=1.8, home_xga=1.8, away_xga=1.8):
    return {"id":tid,"stats":{
        "seasonMatchesPlayed_home":3,"seasonMatchesPlayed_away":3,"seasonMatchesPlayed_overall":6,
        "xg_for_avg_home":home_xg,"xg_for_avg_away":away_xg,"xg_against_avg_home":home_xga,"xg_against_avg_away":away_xga,
        "seasonScoredAVG_home":1.8,"seasonScoredAVG_away":1.8,"seasonConcededAVG_home":1.8,"seasonConcededAVG_away":1.8,
        "shotsAVG_home":14,"shotsAVG_away":14,"shotsOnTargetAVG_home":5,"shotsOnTargetAVG_away":5,
        "seasonBTTSPercentage_home":70,"seasonBTTSPercentage_away":70,"seasonBTTSPercentageHT_home":35,"seasonBTTSPercentageHT_away":35,
        "seasonFTSPercentage_home":10,"seasonFTSPercentage_away":10,"seasonCSPercentage_home":10,"seasonCSPercentage_away":10,
        "seasonOver25Percentage_home":65,"seasonOver25Percentage_away":65,
    }}


def form_row(tid,window,btts=70):
    return {"id":tid,"last_x_match_num":window,"stats":{},
            "xg_for_avg_home":1.8,"xg_for_avg_away":1.8,"xg_against_avg_home":1.8,"xg_against_avg_away":1.8,
            "seasonBTTSPercentage_home":btts,"seasonBTTSPercentage_away":btts,
            "seasonBTTSPercentageHT_home":35,"seasonBTTSPercentageHT_away":35,
            "seasonFTSPercentage_home":10,"seasonFTSPercentage_away":10,
            "seasonCSPercentage_home":10,"seasonCSPercentage_away":10,
            "seasonScoredAVG_home":1.8,"seasonScoredAVG_away":1.8,
            "seasonConcededAVG_home":1.8,"seasonConcededAVG_away":1.8}


def bundle(form_btts=70):
    match={"data":{"id":1,"homeID":10,"awayID":20,"competition_id":99,
                   "team_a_xg_prematch":1.8,"team_b_xg_prematch":1.8,"total_xg_prematch":3.6,
                   "date_unix":int(time.time())+86400}}
    league={"data":[team(10),team(20),team(30,1.5,1.5,1.5,1.5),team(40,1.6,1.6,1.6,1.6)]}
    form={"data":[form_row(t,w,form_btts) for t in (10,20) for w in (5,6,10)]}
    return match,league,form


class StandaloneTests(unittest.TestCase):
    def test_runtime_has_no_v04_imports(self):
        for module in (app_v1,v1):
            tree=ast.parse(inspect.getsource(module))
            names=[]
            for node in ast.walk(tree):
                if isinstance(node,ast.Import): names += [x.name for x in node.names]
                elif isinstance(node,ast.ImportFrom) and node.module: names.append(node.module)
            for forbidden in FORBIDDEN_RUNTIME_MODULES:
                self.assertNotIn(forbidden,names)

    def test_health_declares_standalone(self):
        h=app_v1.health()
        self.assertTrue(h["standalone"])
        self.assertFalse(h["v043_runtime_dependency"])
        self.assertEqual(len(h["expected_sources"]),6)

    def test_probabilities_are_coherent(self):
        p=v1.dixon_coles(1.8,1.8)
        self.assertAlmostEqual(p["home_win"]+p["draw"]+p["away_win"],1.0,places=7)
        self.assertAlmostEqual(p["btts_yes"]+p["btts_no"],1.0,places=7)
        self.assertAlmostEqual(p["over_2_5"]+p["under_2_5"],1.0,places=7)


class GateV1Tests(unittest.TestCase):
    def test_low_sample_btts_3_of_3_can_play(self):
        m,l,f=bundle(70)
        out=v1.analyze(m,l,f)
        self.assertEqual(out["strongest_market"]["family"],"BTTS")
        self.assertEqual(out["sample_security"],"NIEDRIG")
        self.assertEqual(out["gate_v1"]["required"],3)
        self.assertEqual(out["gate_v1"]["core_confirmations"],3)
        self.assertEqual(out["decision"],"SPIELEN")

    def test_low_sample_btts_2_of_3_stays_observe(self):
        m,l,f=bundle(50)
        out=v1.analyze(m,l,f)
        self.assertEqual(out["gate_v1"]["required"],3)
        self.assertEqual(out["gate_v1"]["core_confirmations"],2)
        self.assertEqual(out["decision"],"BEOBACHTEN")


class FullDataExtractionTests(unittest.TestCase):
    def test_overall_table_is_used(self):
        overall=[{"id":10,"position":7}]+[{"id":20+i,"position":i+1} for i in range(6)]
        d={"data":{"all_matches_table_away":[{"id":10,"position":1}],"all_matches_table_overall":overall}}
        rows=v1._table_rows(d)
        self.assertEqual(rows[0]["position"],7)
        self.assertAlmostEqual(v1._table_summary(rows,10)["position_strength"],0.0)

    def test_trend_parser(self):
        t=v1._trend_summary([["chart","Team has picked up 7 points from the last 5 games. That's 1.4 points per game on average. BTTS has landed in an intriguing 5 of those games. Team has scored 7 times in the last 5 fixtures."]])
        self.assertEqual(t["last5_points"],7.0)
        self.assertEqual(t["last5_btts"],5.0)

    def test_player_detail_filters_competition(self):
        d={"players":[{"id":1,"competition_id":99,"club_team_id":10,"position":"Forward","minutes_played_overall":900,"detailed":{"npxg_per_90_overall":0.5}},{"id":1,"competition_id":98,"club_team_id":10,"position":"Forward","minutes_played_overall":900,"detailed":{"npxg_per_90_overall":9.9}}]}
        rows=v1._detail_rows(d,10,99)
        self.assertEqual(len(rows),1)
        self.assertAlmostEqual(v1._detail_summary(rows)["npxg_per90"],0.5)


if __name__=="__main__": unittest.main()
