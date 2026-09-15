import unittest

from full7_legacy5_adapter import adapt_legacy5_report


KO=2000
CAP=1900
MAX=1999


def source(name,endpoint,payload,**meta):
    return {
        "name":name,
        "json":{
            "_footystats_meta":{
                "endpoint":endpoint,
                "captured_at_unix":CAP,
                "kickoff_unix":KO,
                **meta,
            },
            "payload":payload,
        },
    }


def report():
    match={"data":{"id":44,"homeID":10,"awayID":20,"competition_id":30,"date_unix":KO,"refereeID":-1}}
    return {
        "match_id":44,
        "input_files":[
            source("30_LeagueDaten.json","/league-season",{"team_pages":{"data":[{"id":10},{"id":20}]}},season_id=30,max_time=MAX,team_pagination_complete=True),
            source("44_FormDaten.json","/lastx",{"home":{"data":[{"id":10}]},"away":{"data":[{"id":20}]}}),
            source("44_TableDaten.json","/league-tables",{"data":{}},season_id=30,max_time=MAX),
            source("44_PlayerDaten.json","/league-players",{"pages":[]},season_id=30,max_time=MAX,pagination_complete=True),
            source("44_MatchDaten.json","/match",match,match_id=44),
        ],
    }


class Legacy5AdapterTests(unittest.TestCase):
    def test_valid_legacy_report(self):
        out=adapt_legacy5_report(report())
        self.assertEqual(out["quality"]["training_scope"],"BASE5_CORE_ONLY")
        self.assertEqual(out["quality"]["referee_status"],"NOT_CAPTURED_HISTORICALLY")
        self.assertEqual(out["namespaces"]["referee"],{})
        self.assertEqual(out["namespaces"]["manager"],{})

    def test_missing_source_fails(self):
        r=report()
        r["input_files"]=r["input_files"][:-1]
        self.assertRaises(ValueError,adapt_legacy5_report,r)

    def test_post_kickoff_capture_fails(self):
        r=report()
        r["input_files"][0]["json"]["_footystats_meta"]["captured_at_unix"]=KO
        self.assertRaises(ValueError,adapt_legacy5_report,r)

    def test_max_time_after_kickoff_fails(self):
        r=report()
        r["input_files"][2]["json"]["_footystats_meta"]["max_time"]=KO
        self.assertRaises(ValueError,adapt_legacy5_report,r)

    def test_pagination_fails_closed(self):
        r=report()
        r["input_files"][3]["json"]["_footystats_meta"]["pagination_complete"]=False
        self.assertRaises(ValueError,adapt_legacy5_report,r)

    def test_no_referee_backfill(self):
        r=report()
        r["input_files"][-1]["json"]["payload"]["data"]["refereeID"]=123
        out=adapt_legacy5_report(r)
        self.assertEqual(out["identity"]["referee_id"],123)
        self.assertEqual(out["namespaces"]["referee"],{})
        self.assertEqual(out["quality"]["referee_status"],"NOT_CAPTURED_HISTORICALLY")


if __name__=="__main__":
    unittest.main()
