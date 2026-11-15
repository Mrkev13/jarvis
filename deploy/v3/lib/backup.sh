#!/usr/bin/env bash
set -euo pipefail

docker exec \
  -e BACKUP_ENABLED=true \
  -e SCHEDULER_ENABLED=true \
  standa-hub-backend \
  python -c '
import backup_service
from models import BackupLog
from database import SessionLocal

backup_service.BACKUP_ENABLED = True
backup_id = backup_service.run_backup()

with SessionLocal() as db:
    log = db.get(BackupLog, backup_id)
    if log is None or log.status != "success":
        raise SystemExit("Zaloha neuspesna")

print("Backup successful, ID:", backup_id)
'
