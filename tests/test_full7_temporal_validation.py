import unittest

from full7_temporal_validation import chronological_partition, expanding_walk_forward


def rows(n=20):
    return [
        {"match_id":i+1,"kickoff_unix":1000+(i//2)*100}
        for i in range(n)
    ]


class TemporalValidationTests(unittest.TestCase):
    def test_chronological_partition(self):
        s=chronological_partition(rows())
        self.assertEqual(sum(len(v) for v in s["parts"].values()),20)
        self.assertLessEqual(
            s["ranges"]["train"]["last_kickoff_unix"],
            s["ranges"]["development"]["first_kickoff_unix"],
        )
        self.assertLessEqual(
            s["ranges"]["development"]["last_kickoff_unix"],
            s["ranges"]["calibration"]["first_kickoff_unix"],
        )
        self.assertLessEqual(
            s["ranges"]["calibration"]["last_kickoff_unix"],
            s["ranges"]["forward_oos"]["first_kickoff_unix"],
        )

    def test_same_kickoff_not_split(self):
        s=chronological_partition(rows())
        kickoff_to_parts={}
        for name,part in s["parts"].items():
            for r in part:
                kickoff_to_parts.setdefault(r["kickoff_unix"],set()).add(name)
        self.assertTrue(all(len(parts)==1 for parts in kickoff_to_parts.values()))

    def test_duplicate_match_rejected(self):
        x=rows(8)
        x.append(dict(x[0]))
        self.assertRaises(ValueError,chronological_partition,x)

    def test_walk_forward_is_future_only(self):
        wf=expanding_walk_forward(rows(30),fold_count=4)
        self.assertGreaterEqual(wf["fold_count"],1)
        for fold in wf["folds"]:
            self.assertLessEqual(
                fold["train_last_kickoff_unix"],
                fold["validation_first_kickoff_unix"],
            )

    def test_walk_forward_no_same_kickoff_split(self):
        wf=expanding_walk_forward(rows(30),fold_count=3)
        for fold in wf["folds"]:
            train_k={r["kickoff_unix"] for r in fold["train"]}
            val_k={r["kickoff_unix"] for r in fold["validation"]}
            self.assertFalse(train_k & val_k)

    def test_requires_distinct_time_groups(self):
        x=[{"match_id":i,"kickoff_unix":1000} for i in range(10)]
        self.assertRaises(ValueError,chronological_partition,x)


if __name__=="__main__":
    unittest.main()
