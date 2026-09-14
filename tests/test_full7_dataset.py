import copy
import unittest

from full7_dataset import (
    dedupe_latest_strict,
    derive_targets,
    join_results,
    materialize_matrix,
    validate_target_coherence,
)


def row(match_id, kickoff, captured, value, *, strict=True, with_targets=False):
    targets=derive_targets(2,1) if with_targets else None
    return {
        "match_id":match_id,
        "kickoff_unix":kickoff,
        "snapshot_captured_at_unix":captured,
        "strict_pre_match":strict,
        "snapshot_hash":f"{match_id}-{captured}-{value}",
        "features":{"f1":value,"f2":None},
        "targets":targets,
    }


class DatasetTests(unittest.TestCase):
    def test_targets(self):
        t=derive_targets(2,1)
        self.assertEqual(t["home_win"],1)
        self.assertEqual(t["draw"],0)
        self.assertEqual(t["btts_yes"],1)
        self.assertEqual(t["over_2_5"],1)
        validate_target_coherence(t)

    def test_draw_and_under(self):
        t=derive_targets(0,0)
        self.assertEqual(t["draw"],1)
        self.assertEqual(t["btts_no"],1)
        self.assertEqual(t["under_2_5"],1)

    def test_invalid_result(self):
        self.assertRaises(ValueError,derive_targets,-1,0)

    def test_latest_strict_snapshot_is_kept(self):
        rows=[
            row(1,1000,800,1),
            row(1,1000,900,2),
            row(1,1000,1001,3,strict=False),
        ]
        out=dedupe_latest_strict(rows)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["features"]["f1"],2)

    def test_ambiguous_equal_time_is_fatal(self):
        rows=[row(1,1000,900,1),row(1,1000,900,2)]
        self.assertRaises(ValueError,dedupe_latest_strict,rows)

    def test_result_join_detects_conflicts(self):
        rows=[row(1,1000,900,1)]
        results=[
            {"match_id":1,"home_goals":1,"away_goals":0},
            {"match_id":1,"home_goals":0,"away_goals":1},
        ]
        self.assertRaises(ValueError,join_results,rows,results,source_name="test")

    def test_result_join(self):
        rows=[row(1,1000,900,1)]
        out=join_results(rows,[{"match_id":1,"home_goals":1,"away_goals":1}],source_name="verified")
        self.assertEqual(out[0]["targets"]["draw"],1)
        self.assertEqual(out[0]["result_source"],"verified")

    def test_matrix_preserves_missing(self):
        rows=[row(1,1000,900,1,with_targets=True),row(2,2000,1900,2,with_targets=True)]
        m=materialize_matrix(rows,require_targets=True)
        self.assertEqual(m["row_count"],2)
        self.assertEqual(m["feature_count"],2)
        self.assertIsNone(m["X"][0][m["feature_names"].index("f2")])

    def test_matrix_target_required(self):
        self.assertRaises(ValueError,materialize_matrix,[row(1,1000,900,1)],require_targets=True)

    def test_no_input_mutation(self):
        rows=[row(1,1000,900,1)]
        before=copy.deepcopy(rows)
        dedupe_latest_strict(rows)
        self.assertEqual(rows,before)


if __name__=="__main__":
    unittest.main()
