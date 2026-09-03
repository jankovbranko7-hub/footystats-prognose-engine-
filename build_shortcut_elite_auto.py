from __future__ import annotations

import base64
import os
from pathlib import Path

import app
from shortcut_date_auto import PRODUCT_NAME, build_date_auto_shortcut


OUTPUT_PATH = Path(__file__).with_name("FootyStats_Forebet_ELITE_PICKS_unsigned.shortcut")
DEFAULT_BASE_URL = "https://footystats-forebet-auto-v4-test.onrender.com"


def main() -> None:
    base_url = os.environ.get("FOREBET_AUTO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    base = base64.b64decode(app._PREPARED_SHORTCUT_B64)
    payload = build_date_auto_shortcut(base, base_url)
    OUTPUT_PATH.write_bytes(payload)
    print(OUTPUT_PATH)
    print(f"product={PRODUCT_NAME}")
    print("runtime_questions=date_only")
    print("all_matches_checked=true")
    print("saved_decision=SPIELEN_only")
    print("files_per_saved_match=1")
    print("forebet_manual_input=false")


if __name__ == "__main__":
    main()
