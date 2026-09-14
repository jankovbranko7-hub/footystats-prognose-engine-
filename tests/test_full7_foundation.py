import copy, unittest
from full7_foundation import build_bronze, build_gold, build_silver, classify_path, process_full7

KO=2_000_000_000; CAP=KO-100; MAX=KO-1; HOME=101; AWAY=202; SEASON=303; MATCH=404; REF=505

def w(endpoint,payload,**meta):
    return {"_footystats_meta":{"endpoint":endpoint,"captured_at_unix":CAP,"kickoff_unix":KO,**meta},"payload":payload}

def files():
    return [
      {"name":f"{MATCH}_MatchDaten.json","data":w("/match",{"data":{"id":MATCH,"homeID":HOME,"awayID":AWAY,"competition_id":SEASON,"date_unix":KO,"refereeID":REF,"winningTeam":-1}},match_id=MATCH,temporal_mode="PREMATCH_FIELD_WHITELIST")},
      {"name":f"{SEASON}_LeagueDaten.json","data":w("/league-season",{"team_pages":{"data":[{"id":HOME},{"id":AWAY}]}},season_id=SEASON,max_time=MAX,temporal_mode="STRICT_MAX_TIME")},
      {"name":f"{MATCH}_FormDaten.json","data":w("/lastx",{"home":{"data":[{"id":HOME}]},"away":{"data":[{"id":AWAY}]}},season_id=SEASON,temporal_mode="LIVE_CAPTURE_ONLY_NO_MAX_TIME")},
      {"name":f"{MATCH}_TableDaten.json","data":w("/league-tables",{"data":{"all_matches_table_overall":[{"id":HOME},{"id":AWAY}]}},season_id=SEASON,max_time=MAX,temporal_mode="STRICT_MAX_TIME")},
      {"name":f"{MATCH}_PlayerDaten.json","data":w("/league-players",{"pages":[{"data":[{"id":1,"club_team_id":HOME,"position":"F","minutes_played_overall":90},{"id":2,"club_team_id":AWAY,"position":"F","minutes_played_overall":90}],"pager":{"current_page":1,"max_page":1}}]},season_id=SEASON,max_time=MAX,pagination_complete=True,temporal_mode="STRICT_MAX_TIME")},
      {"name":f"{MATCH}_RefereeDaten.json","data":w("/league-referees",{"data":[{"id":REF}]},season_id=SEASON,max_time=MAX,available=True,temporal_mode="STRICT_MAX_TIME")},
      {"name":f"{MATCH}_ManagerDaten.json","data":w("/manager",{"home":{"data":{"id":701}},"away":{"data":{"id":702}}},season_id=SEASON,home_manager_id=701,away_manager_id=702,home_manager_available=True,away_manager_available=True,temporal_mode="LIVE_CAPTURE_ONLY_NO_MAX_TIME")},
    ]

class T(unittest.TestCase):
    def test_valid_reaches_gold(self): self.assertEqual(process_full7(files())["stage"],"GOLD_READY")
    def test_exact_seven(self): self.assertFalse(process_full7(files()[:-1])["ok"])
    def test_endpoint_mismatch(self):
        x=files(); x[0]["data"]["_footystats_meta"]["endpoint"]="/league-tables"; self.assertFalse(process_full7(x)["ok"])
    def test_capture_after_kickoff(self):
        x=files(); x[3]["data"]["_footystats_meta"]["captured_at_unix"]=KO; self.assertFalse(process_full7(x)["ok"])
    def test_max_time_after_kickoff(self):
        x=files(); x[4]["data"]["_footystats_meta"]["max_time"]=KO; self.assertFalse(process_full7(x)["ok"])
    def test_pagination(self):
        x=files(); x[4]["data"]["_footystats_meta"]["pagination_complete"]=False; x[4]["data"]["payload"]["pages"][0]["pager"]={"current_page":1,"max_page":2}; self.assertFalse(process_full7(x)["ok"])
    def test_minus_one_preserved(self):
        b=build_bronze(files()); self.assertEqual(b["artifacts"]["match"]["raw"]["payload"]["data"]["winningTeam"],-1)
    def test_input_not_mutated(self):
        x=files(); y=copy.deepcopy(x); process_full7(x); self.assertEqual(x,y)
    def test_gold_blocked(self):
        x=files(); x[1]["data"]["_footystats_meta"]["season_id"]=999; b=build_bronze(x); s=build_silver(b); self.assertFalse(s["valid"]); self.assertRaises(ValueError,build_gold,b,s)
    def test_registry_blocks_targets_odds_actual(self):
        self.assertEqual(classify_path("match","data.winningTeam",-1)["status"],"TARGET_ONLY")
        self.assertEqual(classify_path("match","data.odds_ft_1",1.8)["status"],"ODDS_BLOCKED")
        self.assertEqual(classify_path("match","data.team_a_xg",0)["status"],"POST_MATCH_BLOCKED")
        self.assertEqual(classify_path("match","data.team_a_xg_prematch",1.4)["status"],"CANDIDATE_DIRECT")

if __name__=="__main__": unittest.main()
