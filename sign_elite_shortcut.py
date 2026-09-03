from __future__ import annotations

import base64
import json
import plistlib
import urllib.error
import urllib.request
from pathlib import Path


UNSIGNED_PATH = Path(__file__).with_name("FootyStats_Forebet_ELITE_V2_1_unsigned.shortcut")
SIGNED_PATH = Path(__file__).with_name("FootyStats_Forebet_ELITE_V2_1.shortcut")
MODULE_PATH = Path(__file__).with_name("elite_signed_shortcut.py")
HUBSIGN_URL = "https://hubsign.routinehub.services/sign"
SHORTCUT_NAME = "FootyStats + Forebet ELITE V2.1"


def main() -> None:
    raw = UNSIGNED_PATH.read_bytes()
    workflow = plistlib.loads(raw)
    xml = plistlib.dumps(workflow, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")

    body = json.dumps(
        {"shortcutName": SHORTCUT_NAME, "shortcut": xml},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        HUBSIGN_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/octet-stream,*/*",
            "Origin": "https://routinehub.co",
            "Referer": "https://routinehub.co/",
            "User-Agent": "FootyStats-Forebet-ELITE-Builder/2.1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            signed = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise SystemExit(f"HubSign HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise SystemExit(f"HubSign request failed: {exc}") from exc

    if not signed.startswith(b"AEA1"):
        preview = signed[:200].decode("utf-8", "replace")
        raise SystemExit(f"HubSign response is not AEA1: {preview}")

    SIGNED_PATH.write_bytes(signed)
    encoded = base64.b64encode(signed).decode("ascii")
    MODULE_PATH.write_text(
        '"""Pre-signed Apple Shortcut payload for the robust ELITE V2.1 workflow."""\n\n'
        f'SIGNED_ELITE_SHORTCUT_B64 = "{encoded}"\n',
        encoding="utf-8",
    )

    print(f"signed={SIGNED_PATH}")
    print(f"bytes={len(signed)}")
    print("magic=AEA1")
    print(f"module={MODULE_PATH}")


if __name__ == "__main__":
    main()
