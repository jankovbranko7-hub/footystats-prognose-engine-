import unittest

from full7_feature_diagnostics import feature_diagnostics


def row(mid,kickoff,features):
    return {
        "match_id":mid,
        "kickoff_unix":kickoff,
        "features":features,
        "feature_owners":{k:"block" for k in features},
    }


class FeatureDiagnosticTests(unittest.TestCase):
    def test_coverage_constant_and_missing(self):
        rows=[
            row(1,100,{"a":1,"b":1,"c":None}),
            row(2,200,{"a":2,"b":1,"c":3}),
            row(3,300,{"a":3,"b":1}),
            row(4,400,{"a":4,"b":1}),
        ]
        d=feature_diagnostics(rows,min_corr_pairs=2,min_coverage_review=0.5)
        s={x["feature"]:x for x in d["feature_stats"]}
        self.assertEqual(s["b"]["status"],"CONSTANT_REVIEW")
        self.assertEqual(s["c"]["status"],"LOW_COVERAGE_REVIEW")
        self.assertEqual(s["a"]["coverage"],1.0)

    def test_exact_duplicates(self):
        rows=[
            row(1,100,{"a":1,"b":1}),
            row(2,200,{"a":2,"b":2}),
            row(3,300,{"a":3,"b":3}),
        ]
        d=feature_diagnostics(rows,min_corr_pairs=2)
        self.assertEqual(d["exact_duplicate_group_count"],1)
        self.assertEqual(sorted(d["exact_duplicate_groups"][0]),["a","b"])

    def test_high_correlation(self):
        rows=[
            row(i,i*100,{"a":float(i),"b":float(i)*2,"c":float((-1)**i)})
            for i in range(1,11)
        ]
        d=feature_diagnostics(rows,min_corr_pairs=5,high_corr_threshold=0.99)
        pairs={(x["a"],x["b"]) for x in d["high_correlation_pairs"]}
        self.assertIn(("a","b"),pairs)

    def test_temporal_coverage(self):
        rows=[
            row(1,100,{"a":1}),
            row(2,200,{"a":1}),
            row(3,300,{"a":None}),
            row(4,400,{"a":None}),
        ]
        d=feature_diagnostics(rows,min_corr_pairs=2,temporal_bucket_count=2)
        s=d["feature_stats"][0]
        self.assertEqual(s["temporal_bucket_coverage"],[1.0,0.0])
        self.assertEqual(s["temporal_coverage_range"],1.0)

    def test_no_auto_activation_policy(self):
        d=feature_diagnostics([],min_corr_pairs=2)
        self.assertIn("never promote",d["policy"]["no_auto_activation"])


if __name__=="__main__":
    unittest.main()
