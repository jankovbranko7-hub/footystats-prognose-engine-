"""Persistent SHA-256 raw cache with request-key lookup."""
from __future__ import annotations
import gzip, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _param_key(endpoint: str, params: dict) -> str:
    clean = {k: params[k] for k in sorted(params) if k != "key"}
    return json.dumps({"endpoint": endpoint, "params": clean}, sort_keys=True, default=str)


class RawCache:
    def __init__(self, cache_dir: Path, index_path: Path):
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = Path(index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._by_key: dict[str, dict] = {}
        self._load_index()

    def _digest_path(self, digest: str) -> Path:
        # Deliberately derive from current ROOT, not an old absolute path from the index.
        return self.root / f"{digest}.json.gz"

    def _load_index(self) -> None:
        if not self.index_path.exists():
            return
        with self.index_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = _param_key(rec.get("endpoint", ""), rec.get("params") or {})
                digest = rec.get("raw_response_sha256")
                if digest and self._digest_path(digest).exists():
                    self._by_key[key] = rec

    def lookup(self, endpoint: str, params: dict) -> tuple[dict, dict] | tuple[None, None]:
        rec = self._by_key.get(_param_key(endpoint, params))
        if not rec:
            return None, None
        path = self._digest_path(rec["raw_response_sha256"])
        if not path.exists():
            return None, None
        with gzip.open(path, "rb") as fh:
            raw = fh.read()
        # Integrity guard: corrupt/mismatched cache entries are never trusted.
        if hashlib.sha256(raw).hexdigest() != rec["raw_response_sha256"]:
            return None, None
        try:
            js = json.loads(raw.decode("utf-8"))
        except Exception:
            return None, None
        return rec, js

    def store(self, raw_bytes: bytes, *, endpoint: str, params: dict) -> tuple[dict[str, Any], Any]:
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
            "max_page": ((js or {}).get("pager") or {}).get("max_page") if isinstance(js, dict) else None,
            "raw_row_count": row_count,
            "cache_created": created,
        }
        key = _param_key(endpoint, rec["params"])
        if key not in self._by_key:
            with self.index_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._by_key[key] = rec
        return rec, js
