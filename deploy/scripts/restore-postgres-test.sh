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

# MRK-101 review: "empty" = no user object at all - relations (tables, views, sequences, materialized views, indexes,
# foreign tables) in any non-system schema, functions, types, extra schemas and extensions besides plpgsql.
# (*.sql files are gitignored on purpose - no dumps in the repository - so the query lives here, between the markers;
#  backend/tests/test_restore_target_empty.py runs exactly this text against a real PostgreSQL.)
OBJECT_COUNT="$(sudo docker exec -i "$CONTAINER" \
  psql -X -v ON_ERROR_STOP=1 -U standa_hub -d standa_hub_restore -tA <<'EMPTY_SQL'
-- MRK-101: number of user objects in the restore target database; restore-postgres-test.sh requires 0.
-- Counts everything a plain SQL dump could collide with, in every non-system schema (fail closed):
-- relations (tables, partitioned tables, views, materialized views, sequences, indexes, foreign tables, composite
-- types), functions/procedures, user types (domains, enums, ranges, base types - not the row types of the relations
-- already counted), schemas other than public, and extensions other than plpgsql.
-- Test: backend/tests/test_restore_target_empty.py runs this text on a real PostgreSQL.
WITH user_ns AS (
  SELECT oid, nspname FROM pg_namespace
  WHERE nspname NOT IN ('pg_catalog', 'information_schema')
    AND nspname NOT LIKE 'pg\_toast%'
    AND nspname NOT LIKE 'pg\_temp\_%'
)
SELECT
  (SELECT count(*) FROM pg_class c JOIN user_ns n ON n.oid = c.relnamespace)
+ (SELECT count(*) FROM pg_proc p JOIN user_ns n ON n.oid = p.pronamespace)
+ (SELECT count(*) FROM pg_type t JOIN user_ns n ON n.oid = t.typnamespace
     WHERE t.typrelid = 0 AND t.typelem = 0)
+ (SELECT count(*) FROM user_ns WHERE nspname <> 'public')
+ (SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql');
EMPTY_SQL
)"

if [[ "$OBJECT_COUNT" != "0" ]]; then
  echo "ERROR: Restore target database is not empty ($OBJECT_COUNT user objects)" >&2
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
