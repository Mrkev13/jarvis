#!/usr/bin/env python3
"""Atomic deployment journal. No Docker or production changes."""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATES = {
    "prepared": {"deploying"},
    "deploying": {"verifying", "rollback_required"},
    "verifying": {"deployed", "rollback_required"},
    "rollback_required": {"rolled_back"},
    "deployed": set(),
    "rolled_back": set(),
}


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )

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
    args = parser.parse_args()

    path = Path(args.journal)

    if not path.is_file():
        raise SystemExit("JOURNAL_NOT_FOUND")

    data = json.loads(path.read_text())
    current = data.get("state")

    if current not in STATES:
        raise SystemExit("INVALID_CURRENT_STATE")

    if args.state not in STATES[current]:
        raise SystemExit(
            f"INVALID_TRANSITION: {current} -> {args.state}"
        )

    data["state"] = args.state
    data["updated_at"] = datetime.now(timezone.utc).isoformat()

    atomic_write(path, data)
    print(f"JOURNAL_UPDATED: {current} -> {args.state}")


if __name__ == "__main__":
    main()
