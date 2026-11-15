#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT="${1:?Usage: restore-postgres-test.sh BACKUP_ROOT RUN_MANIFEST CONTAINER}"
RUN_MANIFEST="${2:?Missing run manifest}"
CONTAINER="${3:?Missing test container}"

if [[ "$CONTAINER" != jarvis-mrk101-restore* ]]; then
  echo "ERROR: Only isolated MRK-101 restore containers are allowed" >&2
  exit 2
fi

if [[ ! -f "$RUN_MANIFEST" ]]; then
  echo "ERROR: Backup manifest not found" >&2
  exit 2
fi

DUMP_FILE="$(python3 - "$BACKUP_ROOT" "$RUN_MANIFEST" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve(strict=True)
manifest = Path(sys.argv[2]).resolve(strict=True)

if not manifest.is_relative_to(root):
    raise SystemExit("Manifest outside backup root")

data = json.loads(manifest.read_text())

if data.get("status") != "success":
    raise SystemExit("Backup run not successful")

dump = (root / data["database"]["filename"]).resolve(strict=True)

if not dump.is_relative_to(root) or not dump.is_file():
    raise SystemExit("Unsafe or missing dump")

if dump.stat().st_size != data["database"]["size"]:
    raise SystemExit("Dump size mismatch")

digest = hashlib.sha256()
with dump.open("rb") as file:
    for chunk in iter(lambda: file.read(1024 * 1024), b""):
        digest.update(chunk)

if digest.hexdigest() != data["database"]["sha256"]:
    raise SystemExit("Dump checksum mismatch")

print(dump)
PY
)"

# Verify the target container before restoring anything.
sudo docker inspect "$CONTAINER" \
  --format '{{json .}}' | python3 -c '
import json
import sys

container = json.load(sys.stdin)
config = container["Config"]
host = container["HostConfig"]

if config["Image"] != "postgres:18.6":
    raise SystemExit("ERROR: Unexpected PostgreSQL image")

if container["Name"] != "/jarvis-mrk101-restore":
    raise SystemExit("ERROR: Unexpected container name")

if container["State"]["Running"] is not True:
    raise SystemExit("ERROR: Test database is not running")

if container.get("Mounts"):
    raise SystemExit("ERROR: Container has persistent mounts")

if host.get("NetworkMode") not in ("none", "jarvis-mrk101-recovery-net"):
    raise SystemExit("ERROR: Unexpected Docker network")

networks = set(
    (container.get("NetworkSettings") or {}).get("Networks") or {}
)
expected = (
    set()
    if host.get("NetworkMode") == "none"
    else {"jarvis-mrk101-recovery-net"}
)
if networks != expected and not (
    host.get("NetworkMode") == "none" and networks == {"none"}
):
    raise SystemExit("ERROR: Unexpected network attachments")

if host.get("PortBindings"):
    raise SystemExit("ERROR: Test database exposes host ports")

tmpfs = host.get("Tmpfs") or {}
if "/var/lib/postgresql" not in tmpfs:
    raise SystemExit("ERROR: Temporary PostgreSQL storage required")

print("ISOLATED_CONTAINER_OK")
'

# Verify database identity using the disposable container.
DB_IDENTITY="$(sudo docker exec "$CONTAINER" \
  psql -X -U standa_hub -d standa_hub_restore \
  -tAc "SELECT current_user || ':' || current_database();")"

if [[ "$DB_IDENTITY" != "standa_hub:standa_hub_restore" ]]; then
  echo "ERROR: Unexpected database identity" >&2
  exit 2
fi

echo "DATABASE_IDENTITY_OK"

TABLE_COUNT="$(sudo docker exec "$CONTAINER" \
  psql -X -U standa_hub -d standa_hub_restore -tAc \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';")"

if [[ "$TABLE_COUNT" != "0" ]]; then
  echo "ERROR: Restore target database is not empty" >&2
  exit 2
fi

echo "EMPTY_DATABASE_OK"
echo "Backup checksum verified."

# This command must only target a disposable test container.
# The database and user must already exist in the container.
gzip -dc -- "$DUMP_FILE" | sudo docker exec -i "$CONTAINER" \
  psql -X -v ON_ERROR_STOP=1 --single-transaction \
  -U standa_hub -d standa_hub_restore

echo "DATABASE_RESTORE_OK"
