#!/usr/bin/env python3
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/srv/standa-hub-data/backups")
MAX_AGE = 24 * 3600

manifests = sorted(
    (ROOT / "runs").glob("backup_*.json"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not manifests:
    sys.exit("BACKUP_NOT_FOUND")

manifest = manifests[0]
data = json.loads(manifest.read_text())

if data.get("status") != "success":
    sys.exit("BACKUP_NOT_SUCCESSFUL")

database = data["database"]

dump = (ROOT / database["filename"]).resolve()
if not dump.is_relative_to(ROOT.resolve()):
    sys.exit("INVALID_BACKUP_PATH")

if not dump.is_file():
    sys.exit("BACKUP_FILE_MISSING")

if dump.stat().st_size != database["size"]:
    sys.exit("BACKUP_SIZE_MISMATCH")

age = datetime.now(timezone.utc).timestamp() - dump.stat().st_mtime

if age < 0 or age > MAX_AGE:
    sys.exit("BACKUP_TOO_OLD")

digest = hashlib.file_digest(
    dump.open("rb"), "sha256"
).hexdigest()

if digest != database["sha256"]:
    sys.exit("BACKUP_CHECKSUM_MISMATCH")

print("BACKUP_VERIFIED")
print(f"BACKUP_AGE_HOURS={age / 3600:.1f}")
