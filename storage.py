"""Tiny JSON-file store for bot state.

The bot is single-process and PTB runs handlers on one event loop, so a
read-modify-write on a plain dict plus an atomic file replace is enough.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# On a server, point DATA_DIR at a persistent volume so verified users and
# attendance history survive restarts and redeploys.
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_FILE = DATA_DIR / "data.json"

EMPTY_STATE = {
    # code -> {"created_at", "used_by", "used_at"}
    "codes": {},
    # str(user_id) -> {"name", "username", "verified_at", "code"}
    "verified_users": {},
    # "YYYY-MM-DD" (Asia/Tashkent) -> [absent student names]
    "attendance": {},
    # str(chat_id) -> {"title", "type", "added_at"} for every group the bot is in
    "groups": {},
    # str(user_id) -> {"chat_id", "message_id", "day"} of their open roster screen
    "open_screens": {},
    # "YYYY-MM-DD" -> {"by", "at"} for days the register was actually taken
    "marked": {},
}


def load() -> dict:
    if not DATA_FILE.exists():
        return json.loads(json.dumps(EMPTY_STATE))
    with DATA_FILE.open(encoding="utf-8") as fh:
        state = json.load(fh)
    for key, default in EMPTY_STATE.items():
        state.setdefault(key, json.loads(json.dumps(default)))
    return state


def save(state: dict) -> None:
    """Write via a temp file + rename so a crash can't truncate data.json.

    The temp file must sit on the same filesystem as the target, or os.replace
    fails across a mounted volume boundary.
    """
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(DATA_FILE.parent), prefix=".data-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, DATA_FILE)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
