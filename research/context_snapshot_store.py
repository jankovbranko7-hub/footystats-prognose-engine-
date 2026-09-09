from __future__ import annotations
import json, os, urllib.error, urllib.parse, urllib.request
from typing import Any, Dict, Mapping, Optional

DEFAULT_TABLE = "footystats_context_snapshots"
VALID_MODES = {"NONE", "SUPABASE"}


def _env(environ: Optional[Mapping[str, str]], key: str) -> str:
    source = os.environ if environ is None else environ
    return str(source.get(key) or "").strip()


def snapshot_store_config(environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    mode = (_env(environ, "CONTEXT_SNAPSHOT_STORE") or "NONE").upper()
    if mode not in VALID_MODES:
        return {"valid": False, "mode": mode, "error": "CONTEXT_SNAPSHOT_STORE must be NONE or SUPABASE"}
    if mode == "NONE":
        return {"valid": True, "mode": "NONE", "durable": False}
    url = _env(environ, "SUPABASE_URL").rstrip("/")
    key = _env(environ, "SUPABASE_SERVICE_ROLE_KEY")
    table = _env(environ, "CONTEXT_SNAPSHOT_TABLE") or DEFAULT_TABLE
    if not url or not key:
        return {"valid": False, "mode": "SUPABASE", "durable": True, "table": table, "error": "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required"}
    return {"valid": True, "mode": "SUPABASE", "durable": True, "url": url, "key": key, "table": table}


def _row(record: Dict[str, Any]) -> Dict[str, Any]:
    match = record.get("match") or {}
    return {
        "record_sha256": record.get("record_sha256"),
        "record_id": record.get("record_id"),
        "match_id": match.get("match_id"),
        "captured_at_utc": record.get("captured_at_utc"),
        "kickoff_at_utc": match.get("kickoff_at_utc"),
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
        "current_context_sha256": record.get("current_context_sha256"),
        "five_file_manifest_sha256": record.get("five_file_manifest_sha256"),
        "snapshot": record,
    }


def persist_context_snapshot(record: Dict[str, Any], *, environ: Optional[Mapping[str, str]] = None, opener=urllib.request.urlopen, timeout: float = 15.0) -> Dict[str, Any]:
    cfg = snapshot_store_config(environ)
    if not cfg.get("valid"):
        return {"status": "CONFIG_ERROR", "mode": cfg.get("mode"), "durable": cfg.get("durable", False), "error": cfg.get("error")}
    if cfg["mode"] == "NONE":
        return {"status": "DISABLED", "mode": "NONE", "durable": False}
    table = cfg["table"]
    query = urllib.parse.urlencode({"on_conflict": "record_sha256"})
    endpoint = f"{cfg['url']}/rest/v1/{urllib.parse.quote(table, safe='')}?{query}"
    body = json.dumps(_row(record), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "apikey": cfg["key"],
            "Authorization": f"Bearer {cfg['key']}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
            "User-Agent": "FootyStats-New-Architecture/0.10",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            if status < 200 or status >= 300:
                return {"status": "FAILED", "mode": "SUPABASE", "durable": True, "table": table, "http_status": status, "error": "non-2xx response"}
    except urllib.error.HTTPError as exc:
        detail = ""
        try: detail = exc.read().decode("utf-8", "replace")[:1000]
        except Exception: pass
        return {"status": "FAILED", "mode": "SUPABASE", "durable": True, "table": table, "http_status": exc.code, "error": detail or str(exc)}
    except Exception as exc:
        return {"status": "FAILED", "mode": "SUPABASE", "durable": True, "table": table, "error": str(exc)}
    return {"status": "PERSISTED", "mode": "SUPABASE", "durable": True, "table": table, "record_sha256": record.get("record_sha256")}
