"""Persistent SHA-256 raw cache with disk-backed request-key lookup."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _param_key(endpoint: str, params: dict) -> str:
    clean = {k: params[k] for k in sorted(params) if k != "key"}
    return json.dumps(
        {"endpoint": endpoint, "params": clean},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )


def _key_hash(key_text: str) -> str:
    return hashlib.sha256(key_text.encode("utf-8")).hexdigest()


class RawCache:
    """Persistent raw-response cache.

    Raw response bodies are stored as gzip files named by SHA-256.
    Request-key lookup is stored in SQLite so the index does not grow without
    bound in process memory during the 17,685-match collection.
    """

    def __init__(self, cache_dir: Path, index_path: Path):
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = self.index_path.with_suffix(self.index_path.suffix + ".sqlite3")
        self.db = sqlite3.connect(self.db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_index (
                key_hash TEXT PRIMARY KEY,
                key_text TEXT NOT NULL,
                rec_json TEXT NOT NULL,
                digest TEXT NOT NULL
            )
            """
        )
        self.db.commit()
        self._migrate_legacy_jsonl_if_needed()

    def _digest_path(self, digest: str) -> Path:
        return self.root / f"{digest}.json.gz"

    def _migrate_legacy_jsonl_if_needed(self) -> None:
        row = self.db.execute("SELECT COUNT(*) FROM cache_index").fetchone()
        if row and int(row[0]) > 0:
            return
        if not self.index_path.exists():
            return

        batch = []
        with self.index_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                digest = rec.get("raw_response_sha256")
                if not digest or not self._digest_path(digest).exists():
                    continue
                key_text = _param_key(rec.get("endpoint", ""), rec.get("params") or {})
                batch.append(
                    (
                        _key_hash(key_text),
                        key_text,
                        json.dumps(rec, ensure_ascii=False, separators=(",", ":")),
                        digest,
                    )
                )
                if len(batch) >= 500:
                    self.db.executemany(
                        "INSERT OR REPLACE INTO cache_index(key_hash,key_text,rec_json,digest) VALUES(?,?,?,?)",
                        batch,
                    )
                    self.db.commit()
                    batch.clear()
        if batch:
            self.db.executemany(
                "INSERT OR REPLACE INTO cache_index(key_hash,key_text,rec_json,digest) VALUES(?,?,?,?)",
                batch,
            )
            self.db.commit()

    def lookup(self, endpoint: str, params: dict) -> tuple[dict, dict] | tuple[None, None]:
        key_text = _param_key(endpoint, params)
        row = self.db.execute(
            "SELECT key_text, rec_json, digest FROM cache_index WHERE key_hash=?",
            (_key_hash(key_text),),
        ).fetchone()
        if not row or row[0] != key_text:
            return None, None

        rec = json.loads(row[1])
        digest = row[2]
        path = self._digest_path(digest)
        if not path.exists():
            return None, None

        with gzip.open(path, "rb") as fh:
            raw = fh.read()
        if hashlib.sha256(raw).hexdigest() != digest:
            return None, None
        try:
            js = json.loads(raw.decode("utf-8"))
        except Exception:
            return None, None
        return rec, js

    def store(
        self,
        raw_bytes: bytes,
        *,
        endpoint: str,
        params: dict,
    ) -> tuple[dict[str, Any], Any]:
        digest = hashlib.sha256(raw_bytes).hexdigest()
        cache_path = self._digest_path(digest)
        created = False
        if not cache_path.exists():
            with gzip.open(cache_path, "wb") as fh:
                fh.write(raw_bytes)
            created = True

        try:
            js = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            js = None

        row_count = None
        if isinstance(js, dict) and isinstance(js.get("data"), list):
            row_count = len(js["data"])
        elif isinstance(js, dict):
            row_count = 1

        rec = {
            "endpoint": endpoint,
            "params": {k: v for k, v in params.items() if k != "key"},
            "requested_max_time": params.get("max_time"),
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "raw_response_sha256": digest,
            "cache_file": f"raw_cache/{digest}.json.gz",
            "page": params.get("page"),
            "max_page": ((js or {}).get("pager") or {}).get("max_page")
            if isinstance(js, dict)
            else None,
            "raw_row_count": row_count,
            "cache_created": created,
        }

        key_text = _param_key(endpoint, rec["params"])
        key_hash = _key_hash(key_text)
        existed = self.db.execute(
            "SELECT 1 FROM cache_index WHERE key_hash=?",
            (key_hash,),
        ).fetchone() is not None

        self.db.execute(
            "INSERT OR REPLACE INTO cache_index(key_hash,key_text,rec_json,digest) VALUES(?,?,?,?)",
            (
                key_hash,
                key_text,
                json.dumps(rec, ensure_ascii=False, separators=(",", ":")),
                digest,
            ),
        )
        self.db.commit()

        # Keep the human-readable append-only provenance index, but do not load
        # it into RAM. Existing tooling can continue to inspect this file.
        if not existed:
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        return rec, js

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass

    def __del__(self):
        self.close()
