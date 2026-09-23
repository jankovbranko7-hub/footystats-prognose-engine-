#!/usr/bin/env python3
"""Read-only streaming recovery export for the frozen FULL-7 raw snapshot.

Creates no collection/API data and does not rebuild any research phase.
The verified /var/data/full7 tree is partitioned into 14 deterministic file
lists. Each requested part is tar-streamed and encrypted independently with
AES-256-CBC/PBKDF2, so no 11+ GB duplicate needs to be stored on the Render disk.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

DATA_ROOT = Path("/var/data/full7")
WORK_ROOT = Path("/var/data/full7_recovery_export_2026-09-23")
SOURCE_MANIFEST = DATA_ROOT / "FULL7_BACKUP_SHA256_MANIFEST.tsv"
SOURCE_INVENTORY = DATA_ROOT / "FULL7_BACKUP_INVENTORY.json"

EXPECTED_MANIFEST_SHA256 = "86c05accd2f1cb56e5afed13057b5dbb2e857e847b5dd75d927863e7879999d6"
EXPECTED_INVENTORY_SHA256 = "ebe438fbacf2d35315bd2ed7d80dac2ed44468e0e3ada9d1d98ead066b91a304"
EXPECTED_MANIFEST_ENTRIES = 217258
EXPECTED_MANIFEST_ENTRY_BYTES = 10993329748
EXPECTED_SOURCE_FILE_COUNT = 217260
EXPECTED_SOURCE_TOTAL_BYTES = 11023029301
PART_COUNT = 14
PBKDF2_ITERATIONS = 200000
PORT = 8765

class ExportError(RuntimeError):
    pass

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _require_runtime() -> None:
    if os.environ.get("RENDER_SERVICE_ID") != "srv-damiu0p42hec739a0rig":
        raise ExportError("wrong_render_service")
    if os.environ.get("RENDER_GIT_BRANCH") != "audit/full7-cp2-20260922":
        raise ExportError("wrong_git_branch")
    if os.environ.get("RUN_FULL7_BACKUP_STREAM_SERVER", "false").strip().lower() != "true":
        raise ExportError("stream_server_flag_not_enabled")

def _load_verified_records() -> list[tuple[str, int, str]]:
    if _sha256(SOURCE_MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise ExportError("source_manifest_sha_mismatch")
    if _sha256(SOURCE_INVENTORY) != EXPECTED_INVENTORY_SHA256:
        raise ExportError("source_inventory_sha_mismatch")

    records: list[tuple[str, int, str]] = []
    total = 0
    with SOURCE_MANIFEST.open("r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n")
        if header != "sha256\tsize_bytes\trelative_path":
            raise ExportError("unexpected_manifest_header")
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            sha, size_text, rel = line.split("\t", 2)
            size = int(size_text)
            path = DATA_ROOT / rel
            if not path.is_file() or path.stat().st_size != size:
                raise ExportError(f"source_missing_or_size_bad:{rel}")
            records.append((rel, size, sha))
            total += size
    if len(records) != EXPECTED_MANIFEST_ENTRIES or total != EXPECTED_MANIFEST_ENTRY_BYTES:
        raise ExportError("manifest_population_mismatch")

    # The source manifest intentionally excludes these two files.
    records.append((
        "FULL7_BACKUP_INVENTORY.json",
        SOURCE_INVENTORY.stat().st_size,
        EXPECTED_INVENTORY_SHA256,
    ))
    records.append((
        "FULL7_BACKUP_SHA256_MANIFEST.tsv",
        SOURCE_MANIFEST.stat().st_size,
        EXPECTED_MANIFEST_SHA256,
    ))
    if len(records) != EXPECTED_SOURCE_FILE_COUNT:
        raise ExportError("source_file_count_mismatch")
    if sum(item[1] for item in records) != EXPECTED_SOURCE_TOTAL_BYTES:
        raise ExportError("source_total_bytes_mismatch")
    return sorted(records, key=lambda item: item[0])

def _partition(records: list[tuple[str, int, str]]) -> list[list[tuple[str, int, str]]]:
    total = sum(item[1] for item in records)
    parts: list[list[tuple[str, int, str]]] = []
    current: list[tuple[str, int, str]] = []
    cumulative = 0
    next_boundary = total / PART_COUNT

    for record in records:
        if current and len(parts) < PART_COUNT - 1 and cumulative >= next_boundary:
            parts.append(current)
            current = []
            next_boundary = total * (len(parts) + 1) / PART_COUNT
        current.append(record)
        cumulative += record[1]
    if current:
        parts.append(current)
    if len(parts) != PART_COUNT:
        raise ExportError(f"partition_count_mismatch:{len(parts)}")
    return parts

def _write_metadata(parts: list[list[tuple[str, int, str]]]) -> dict[str, Any]:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    key_path = WORK_ROOT / "FULL7_RECOVERY_KEY.txt"
    token_path = WORK_ROOT / ".download_token"
    if not key_path.exists():
        key_path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    if not token_path.exists():
        token_path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
        token_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    part_info = []
    for idx, group in enumerate(parts):
        name = f"part-{idx:04d}.tar.enc"
        list_path = WORK_ROOT / f"part-{idx:04d}.lst"
        list_path.write_text("".join(rel + "\n" for rel, _size, _sha in group), encoding="utf-8")
        part_info.append({
            "name": name,
            "file_count": len(group),
            "source_bytes": sum(size for _rel, size, _sha in group),
            "list_sha256": _sha256(list_path),
            "first_path": group[0][0],
            "last_path": group[-1][0],
        })

    index = {
        "format": "FULL7_RECOVERY_STREAMED_TAR_AES256_PBKDF2_V1",
        "created_for": "FULL7 frozen raw snapshot recovery",
        "source": {
            "root": str(DATA_ROOT),
            "file_count": EXPECTED_SOURCE_FILE_COUNT,
            "total_bytes": EXPECTED_SOURCE_TOTAL_BYTES,
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "inventory_sha256": EXPECTED_INVENTORY_SHA256,
        },
        "archive": {
            "part_count": PART_COUNT,
            "tar_mode": "independent_part_tar",
            "encryption": "openssl aes-256-cbc -salt -pbkdf2",
            "pbkdf2_iterations": PBKDF2_ITERATIONS,
            "compression": "none",
            "path_order": "UTF-8 relative path ascending",
        },
        "parts": part_info,
        "collection_performed": False,
        "api_calls_performed": False,
        "cp1_cp7_reexecuted": False,
        "main_changed": False,
        "production_changed": False,
    }
    index_path = WORK_ROOT / "FULL7_RECOVERY_EXPORT_INDEX.json"
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return index

def _ensure_cloudflared() -> Path:
    existing = shutil.which("cloudflared")
    if existing:
        return Path(existing)
    target = WORK_ROOT / "cloudflared"
    if not target.exists():
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        urllib.request.urlretrieve(url, target)
        target.chmod(0o700)
    return target

def _launch_tunnel(cloudflared: Path, token: str) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            match = pattern.search(line)
            if match:
                print(f"FULL7_RECOVERY_DOWNLOAD_BASE={match.group(0)}/{token}/", flush=True)
            elif "ERR" in line or "error" in line.lower():
                print("FULL7_RECOVERY_TUNNEL_LOG=" + line.strip(), flush=True)
    threading.Thread(target=reader, daemon=True).start()
    return proc

def _stream_part(handler: http.server.BaseHTTPRequestHandler, idx: int) -> None:
    list_path = WORK_ROOT / f"part-{idx:04d}.lst"
    key_path = WORK_ROOT / "FULL7_RECOVERY_KEY.txt"
    if not list_path.is_file():
        handler.send_error(404)
        return

    handler.send_response(200)
    handler.send_header("Content-Type", "application/octet-stream")
    handler.send_header("Content-Disposition", f'attachment; filename="part-{idx:04d}.tar.enc"')
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()

    tar = subprocess.Popen(
        ["tar", "-C", str(DATA_ROOT), "-cf", "-", "-T", str(list_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert tar.stdout is not None
    enc = subprocess.Popen(
        [
            "openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2",
            "-iter", str(PBKDF2_ITERATIONS), "-pass", f"file:{key_path}",
        ],
        stdin=tar.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tar.stdout.close()
    assert enc.stdout is not None

    try:
        while True:
            block = enc.stdout.read(1024 * 1024)
            if not block:
                break
            handler.wfile.write(block)
    except (BrokenPipeError, ConnectionResetError):
        enc.kill()
        tar.kill()
        raise
    finally:
        enc.stdout.close()

    enc_rc = enc.wait()
    tar_rc = tar.wait()
    if enc_rc != 0 or tar_rc != 0:
        enc_err = (enc.stderr.read() if enc.stderr else b"").decode("utf-8", "replace")
        tar_err = (tar.stderr.read() if tar.stderr else b"").decode("utf-8", "replace")
        print(
            "FULL7_RECOVERY_STREAM_ERROR="
            + json.dumps({"part": idx, "tar_rc": tar_rc, "enc_rc": enc_rc,
                          "tar_err": tar_err[-1000:], "enc_err": enc_err[-1000:]}),
            flush=True,
        )
    else:
        print(f"FULL7_RECOVERY_STREAM_COMPLETE=part-{idx:04d}.tar.enc", flush=True)

def run_stream_server() -> None:
    _require_runtime()
    records = _load_verified_records()
    parts = _partition(records)
    index = _write_metadata(parts)
    token = (WORK_ROOT / ".download_token").read_text(encoding="utf-8").strip()
    cloudflared = _ensure_cloudflared()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return
        def do_GET(self) -> None:
            prefix = f"/{token}/"
            if not self.path.startswith(prefix):
                self.send_error(404)
                return
            leaf = self.path[len(prefix):].split("?", 1)[0]
            if leaf == "index.json":
                payload = json.dumps(index, indent=2, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
                return
            if leaf == "recovery.key":
                payload = (WORK_ROOT / "FULL7_RECOVERY_KEY.txt").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
                return
            match = re.fullmatch(r"part-(\d{4})\.tar\.enc", leaf)
            if match:
                idx = int(match.group(1))
                if 0 <= idx < PART_COUNT:
                    _stream_part(self, idx)
                    return
            self.send_error(404)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    tunnel = _launch_tunnel(cloudflared, token)
    print(
        "FULL7_RECOVERY_STREAM_READY="
        + json.dumps({
            "part_count": PART_COUNT,
            "source_file_count": EXPECTED_SOURCE_FILE_COUNT,
            "source_total_bytes": EXPECTED_SOURCE_TOTAL_BYTES,
            "work_root": str(WORK_ROOT),
            "free_bytes": shutil.disk_usage("/var/data").free,
        }, sort_keys=True),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        tunnel.terminate()

def main() -> None:
    run_stream_server()

if __name__ == "__main__":
    main()
