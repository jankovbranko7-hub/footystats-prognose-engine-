"""Synthetic safety tests, not performance evidence."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from pydantic import ValidationError
from full5_pipeline.audit import DataError, decode, inventory
from full5_pipeline.snapshots import Snapshot, validate_bundle
from full5_pipeline.temporal import MatchRow, split_matches

T = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def bundle():
    result = []
    for source, endpoint in [("MATCH", "match"), ("LEAGUE", "league-season"),
                             ("FORM", "lastx"), ("TABLE", "league-tables"),
                             ("PLAYER", "league-players")]:
        payload = {"data": {"id": 1, "homeID": 2, "awayID": 3,
                           "date_unix": int(T.timestamp()), "status": "incomplete"}}
        raw = json.dumps(payload).encode()
        meta = Snapshot(source=source, endpoint=endpoint, match_id=1, season_id=4,
                        home_id=2, away_id=3, kickoff=T,
                        requested_at=T-timedelta(hours=2),
                        received_at=T-timedelta(hours=1), raw_sha256=sha256(raw).hexdigest())
        result.append((meta, raw))
    return result


class JsonTests(unittest.TestCase):
    def test_duplicate_key(self):
        with self.assertRaises(DataError):
            decode(b'{"x": 1, "x": 2}')

    def test_invalid_and_nonfinite(self):
        for raw in (b'{"x": NaN}', b'{"x": Infinity}', b'{"x": 1e999}',
                    b'not json', b'[]', b'null', b'{}', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(DataError):
                decode(raw)

    def test_depth(self):
        with self.assertRaises(DataError):
            decode(b"["*70 + b"0" + b"]"*70)

    def test_inventory_keeps_all_leaves(self):
        report = inventory("FORM", b'{"a/b": [null, 0, false, {}, []], "~": "secret"}')
        self.assertEqual(report["leaf_count"], 6)
        self.assertEqual(report["approved_feature_count"], 0)
        self.assertEqual(report["fields"][0]["pointer"], "/a~1b/0")
        self.assertEqual(report["fields"][-1]["pointer"], "/~0")
        self.assertEqual(report["fields"][2]["type"], "boolean")
        self.assertNotIn("secret", json.dumps(report))

    def test_zero_is_not_missing(self):
        report = inventory("MATCH", b'{"x": 0, "y": null}')
        self.assertFalse(report["fields"][0]["missing"])
        self.assertTrue(report["fields"][1]["missing"])


class SnapshotTests(unittest.TestCase):
    def test_safe_default(self):
        report = validate_bundle(bundle(), now=T)
        self.assertEqual(report["capture_timing"], "BEFORE_KICKOFF")
        self.assertFalse(report["strict_prematch_certified"])
        self.assertFalse(report["training_ready"])
        self.assertEqual(report["decision"], "AUSLASSEN")

    def test_exactly_five_unique_sources(self):
        for items in (bundle()[:4], bundle()+[bundle()[0]], [bundle()[0]]*5):
            with self.subTest(count=len(items)), self.assertRaises(DataError):
                validate_bundle(items, now=T)

    def test_tampering(self):
        items = bundle()
        items[0] = (items[0][0], b'{"changed": true}')
        with self.assertRaises(DataError):
            validate_bundle(items, now=T)

    def test_identity(self):
        items = bundle()
        raw = items[0][1].replace(b'"homeID": 2', b'"homeID": 8')
        data = items[0][0].model_dump()
        data["raw_sha256"] = sha256(raw).hexdigest()
        items[0] = (Snapshot(**data), raw)
        with self.assertRaises(DataError):
            validate_bundle(items, now=T)

    def test_naive_timestamp(self):
        data = bundle()[0][0].model_dump()
        data["received_at"] = T.replace(tzinfo=None)
        with self.assertRaises(ValidationError):
            Snapshot(**data)

    def test_lastx_max_time_rejected(self):
        data = bundle()[2][0].model_dump()
        data["requested_max_time"] = int(T.timestamp())-1
        with self.assertRaises(ValidationError):
            Snapshot(**data)

    def test_historical_capture_not_certified(self):
        items = []
        for meta, raw in bundle():
            data = meta.model_dump()
            data["received_at"] = T+timedelta(seconds=1)
            items.append((Snapshot(**data), raw))
        report = validate_bundle(items, now=T+timedelta(days=1))
        self.assertEqual(report["capture_timing"], "HISTORICAL_UNVERIFIED")
        self.assertFalse(report["training_ready"])

    def test_future_capture(self):
        with self.assertRaises(DataError):
            validate_bundle(bundle(), now=T-timedelta(days=1))

    def test_provider_error(self):
        items = bundle()
        meta = items[1][0]
        raw = b'{"success": false, "message": "private"}'
        items[1] = (Snapshot(**{**meta.model_dump(), "raw_sha256": sha256(raw).hexdigest()}), raw)
        with self.assertRaises(DataError):
            validate_bundle(items, now=T)


class TemporalTests(unittest.TestCase):
    def row(self, match_id, days):
        start = T+timedelta(days=days)
        return MatchRow(match_id, start, start-timedelta(hours=1),
                        start+timedelta(hours=3))

    def split(self, rows):
        return split_matches(rows, train_end=T+timedelta(days=2),
                             development_end=T+timedelta(days=4),
                             evaluation_as_of=T+timedelta(days=6))

    def test_date_blocks(self):
        result = self.split([self.row(3, 4), self.row(1, 0), self.row(2, 2)])
        self.assertEqual(result["train"], [1])
        self.assertEqual(result["development"], [2])
        self.assertEqual(result["test"], [3])

    def test_duplicate_match_id(self):
        with self.assertRaises(DataError):
            self.split([self.row(1, 0), self.row(1, 1)])

    def test_label_delay(self):
        row = MatchRow(1, T, T-timedelta(hours=1), T+timedelta(days=3))
        result = self.split([row])
        self.assertEqual(result["train"], [])
        self.assertEqual(result["excluded"][0]["reason"], "LABEL_NOT_AVAILABLE_AT_BOUNDARY")

    def test_after_kickoff_capture(self):
        row = MatchRow(1, T, T, T+timedelta(hours=3))
        self.assertEqual(self.split([row])["excluded"][0]["reason"], "NOT_PREMATCH_CAPTURE")


if __name__ == "__main__":
    unittest.main()
