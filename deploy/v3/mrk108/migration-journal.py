#!/usr/bin/env python3
"""MRK-114: atomic journal of a controlled migration deployment (deploy-migration-v3.sh). No Docker or DB access.

prepared -> rehearsed -> db_migrating -> db_migrated -> deploying -> verifying -> deployed
Failure paths: prepared/rehearsed -> aborted (nothing changed); db_migrating -> aborted only after the production
database is verified still at the old head, or -> db_migrated when it is verified at the new head;
deploying/verifying -> app_rollback_required -> rolled_back_app (old application on the migrated database, only after
its compatibility check passed). The database is never downgraded.
"""
import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATES = {
    "prepared": {"rehearsed", "aborted"},
    "rehearsed": {"db_migrating", "aborted"},
    "db_migrating": {"db_migrated", "aborted"},
    "db_migrated": {"deploying"},
    "deploying": {"verifying", "app_rollback_required"},
    "verifying": {"deployed", "app_rollback_required"},
    "app_rollback_required": {"rolled_back_app"},
    "deployed": set(),
    "aborted": set(),
    "rolled_back_app": set(),
}
TERMINAL = {state for state, nxt in STATES.items() if not nxt}


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("journal")
    parser.add_argument("state")
    parser.add_argument("--note", default=None, help="short reason stored with the transition")
    args = parser.parse_args()
    path = Path(args.journal)
    if not path.is_file():
        raise SystemExit("JOURNAL_NOT_FOUND")
    data = json.loads(path.read_text())
    current = data.get("state")
    if current not in STATES:
        raise SystemExit("INVALID_CURRENT_STATE")
    if args.state not in STATES[current]:
        raise SystemExit(f"INVALID_TRANSITION: {current} -> {args.state}")
    now = datetime.now(timezone.utc).isoformat()
    data["state"] = args.state
    data["updated_at"] = now
    data.setdefault("history", []).append({"state": args.state, "at": now, **({"note": args.note} if args.note else {})})
    atomic_write(path, data)
    print(f"MIGRATION_JOURNAL_UPDATED: {current} -> {args.state}")


if __name__ == "__main__":
    main()
