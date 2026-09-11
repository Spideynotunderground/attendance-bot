#!/usr/bin/env python3
"""Show every access code and its status.

    python codes.py            every code: UNUSED / USED / REVOKED
    python codes.py --unused   just the codes you can still hand out

Reads the same files the bot does. The bot applies access_codes.txt and
revoked_codes.txt on a 60-second refresh; a code listed there that it hasn't
picked up yet is shown as pending — so a code shows as REVOKED the moment you
run the revoke command, not a minute later.
"""

import os
import sys

import storage


def read_code_file(path) -> list:
    """One code per line; '#' starts a comment. Same rules as the bot."""
    if not path.exists():
        return []
    codes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            codes.append(line)
    return codes


def who(entry: dict, users: dict) -> str:
    uid = entry.get("used_by")
    known = users.get(str(uid)) or {}
    name = entry.get("used_by_name") or known.get("name")
    username = entry.get("used_by_username") or known.get("username")
    label = name or f"user {uid}"
    return f"{label} (@{username})" if username else label


def statuses(state: dict, revoked_listed, added_listed) -> list:
    """[(code, status)] — registered codes first, then ones not picked up yet."""
    users = state.get("verified_users", {})
    codes = state.get("codes", {})
    revoked_listed = set(revoked_listed)
    rows = []

    for code, entry in codes.items():
        used = entry.get("used_by") is not None
        if entry.get("revoked"):
            status = f"REVOKED  (was used by {who(entry, users)})" if used else "REVOKED"
        elif code in revoked_listed:
            status = "REVOKED  (pending — the bot blocks it within a minute)"
        elif used:
            status = f"USED     by {who(entry, users)}"
        else:
            status = "UNUSED"
        rows.append((code, status))

    seen = set(codes)
    for code in added_listed:
        if code in seen:
            continue
        seen.add(code)
        if code in revoked_listed:
            rows.append((code, "REVOKED  (pending — will never become usable)"))
        else:
            rows.append((code, "NEW      (pending — usable within a minute)"))
    for code in revoked_listed - seen:
        rows.append((code, "REVOKED  (pending — will never become usable)"))
    return rows


def main(argv) -> int:
    data_dir = storage.DATA_FILE.parent
    state = storage.load()
    revoked = read_code_file(data_dir / "revoked_codes.txt")
    env_codes = os.environ.get("ACCESS_CODES", "").replace(",", " ").split()
    added = env_codes + read_code_file(data_dir / "access_codes.txt")
    rows = statuses(state, revoked, added)

    if "--unused" in argv:
        unused = [code for code, status in rows if status == "UNUSED"]
        print(f"{len(unused)} unused:")
        print("\n".join(unused) if unused else "(none)")
        return 0

    if not rows:
        print("No codes yet.")
        return 0
    width = max(len(code) for code, _ in rows)
    for code, status in rows:
        print(f"{code:<{width}}  {status}")

    counts = {}
    for _, status in rows:
        key = status.split()[0]
        counts[key] = counts.get(key, 0) + 1
    order = ["UNUSED", "USED", "REVOKED", "NEW"]
    print("\n" + " · ".join(f"{counts[k]} {k.lower()}" for k in order if k in counts))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
