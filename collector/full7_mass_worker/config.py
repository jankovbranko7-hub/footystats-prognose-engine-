"""FULL-7 V3 collector configuration. No secrets are stored in code."""
from pathlib import Path
import os

API_BASE = "https://api.football-data-api.com"
API_KEY_ENV = "FOOTYSTATS_API_KEY"

ROOT = Path(os.environ.get("FULL7_ROOT", str(Path(__file__).resolve().parent / "out")))
CSV_PATH = Path(os.environ.get("FULL7_CSV", str(Path(__file__).resolve().parent / "input" / "full7_targets_17685_min.csv")))

RAW_DIR = ROOT / "raw_cache"
MATCH_DIR = ROOT / "matches"
QUAR_DIR = ROOT / "quarantine"
STATE_PATH = ROOT / "state.json"
DONE_PATH = ROOT / "done_ids.txt"
PROGRESS_PATH = ROOT / "progress.jsonl"
CACHE_INDEX = ROOT / "raw_cache_index.jsonl"

SLEEP_S = float(os.environ.get("FULL7_SLEEP", "0.22"))
REQUEST_TIMEOUT = int(os.environ.get("FULL7_TIMEOUT", "90"))
EXPECTED_TOTAL = int(os.environ.get("FULL7_EXPECTED_TOTAL", "17685"))
MIN_FREE_GB = float(os.environ.get("FULL7_MIN_FREE_GB", "0.75"))

REQUIRED_CSV_COLUMNS = ["match_id", "season_id"]
