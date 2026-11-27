"""MRK-151: oznámení „Hub aktualizován“ po nasazení nové verze.

Backend v produkci běží s `APP_COMMIT` (40 hex, nastavuje šablona nasazení). Při startu na commitu, o kterém ještě
žádné oznámení není, vznikne jedno systémové oznámení typu `ops_alert` – zvoneček a Web Push (MRK-24, `OPS_ALERT_PUSH`).
Klíč `deploy:<commit>` zaručí nejvýš jedno oznámení na verzi (restart na stejném commitu nic nepošle) a starší oznámení
o nasazení se vyřeší, ať ve zvonečku visí jen poslední. Text je pevný: jen zkrácený commit, žádná tajemství ani host.
Bez `APP_COMMIT` (lokální vývoj, testy) se nic neděje.

Zastavené nasazení (MRK-151, část 2): updater na serveru po každém běhu zapíše stavový soubor (bez tajemství) do
adresáře, který backend vidí (`UPDATER_STATUS_FILE`, výchozí `/data/backups/ops/updater-status.json`).
`check_updater_status` (hodinový job) z něj pošle jedno oznámení „Nasazení čeká na migraci“ / „Nasazení se zastavilo“
na cílový commit a po úspěšném nasazení ho vyřeší. Důvod je jen kód z allowlistu, text oznámení je pevný.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from env_config import env_str
from models import Notification
from time_utils import utc_now

SOURCE_TYPE = "deploy"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def announce_deploy(db: Session, commit: str | None = None) -> bool:
    """True = vzniklo nové oznámení. Nic necommituje."""
    commit = (commit if commit is not None else env_str("APP_COMMIT")).strip().lower()
    if not COMMIT_RE.match(commit):
        return False
    key = f"deploy:{commit}"
    if db.query(Notification.id).filter(Notification.dedupe_key == key).first():
        return False
    now = utc_now()
    for old in db.query(Notification).filter(Notification.source_type == SOURCE_TYPE,
                                             Notification.resolved == False):  # noqa: E712
        old.resolved = True
    db.add(Notification(area="system", title="Hub aktualizován", message=f"Běží nová verze {commit[:7]}.",
                        severity="info", read=False, created_at=now, notification_type="ops_alert",
                        source_type=SOURCE_TYPE, source_id=None, dedupe_key=key, last_triggered_at=now,
                        resolved=False, action_url="/"))
    db.flush()
    return True


def announce_from_env(session_factory) -> None:
    """Volá se při startu backendu; chyba nesmí start shodit."""
    db = session_factory()
    try:
        if announce_deploy(db):
            db.commit()
            print("[deploy] announced new version")
    except Exception:  # noqa: BLE001 - oznámení je jen informace
        db.rollback()
        print("[deploy] announce failed")
    finally:
        db.close()


# ---------- zastavené nasazení (stav z updateru) ----------

BLOCKED_SOURCE = "deploy_blocked"
STATUS_MAX_BYTES = 4096
STATUS_MAX_AGE = timedelta(hours=2)  # updater běží každých 10 min; starší soubor = updater neběží, nic nehlásit
REASONS = {
    "MIGRATION_HEAD_CHANGED": ("Nasazení čeká na migraci",
                               "Nová verze mění databázi – spusť ruční migraci (deploy-migration-v3.sh --check / --apply)."),
    "BACKUP_NOT_FRESH": ("Nasazení se zastavilo", "Chybí čerstvá ověřená záloha – updater nic nenasadí."),
    "DEPLOY_FAILED": ("Nasazení se nepovedlo", "Updater nové verze skončil chybou – podrobnosti v journalu updateru."),
}
# Stav „waiting“ (CI nové verze ještě běží) i jiné neznámé stavy se ignorují – nic nehlásit, nic nevyřešit.


def _status_path() -> str:
    # zapisuje deploy/v3/lib/updater-status-v3.sh do /srv/standa-hub-data/backups/ops (už připojené jako /data/backups;
    # backend ho jen čte, žádná změna compose šablony)
    return env_str("UPDATER_STATUS_FILE", "/data/backups/ops/updater-status.json")


def read_updater_status(path: str | None = None, now: datetime | None = None) -> dict | None:
    """{'state': 'blocked'|'ok', 'reason', 'target'} nebo None (soubor chybí, je starý nebo neplatný)."""
    path = path or _status_path()
    now = now or utc_now()
    try:
        if os.path.getsize(path) > STATUS_MAX_BYTES:
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        at = datetime.fromisoformat(str(data.get("at", "")).replace("Z", "+00:00"))
    except (OSError, ValueError, TypeError):
        return None
    if at.tzinfo is not None:  # v DB i tady naive UTC
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    state, reason, target = data.get("state"), data.get("reason"), str(data.get("target", "")).lower()
    if now - at > STATUS_MAX_AGE or state not in ("blocked", "ok") or not COMMIT_RE.match(target):
        return None
    if state == "blocked" and reason not in REASONS:
        reason = "DEPLOY_FAILED"
    return {"state": state, "reason": reason if state == "blocked" else None, "target": target}


def check_updater_status(db: Session, path: str | None = None, now: datetime | None = None) -> str:
    """Hodinový krok. → 'none' | 'blocked' | 'resolved'. Nic necommituje."""
    status = read_updater_status(path, now)
    if status is None:
        return "none"
    open_blocked = db.query(Notification).filter(Notification.source_type == BLOCKED_SOURCE,
                                                 Notification.resolved == False).all()  # noqa: E712
    if status["state"] == "ok":
        for n in open_blocked:
            n.resolved = True
        db.flush()
        return "resolved" if open_blocked else "none"
    key = f"deploy-blocked:{status['target']}:{status['reason']}"
    if db.query(Notification.id).filter(Notification.dedupe_key == key).first():
        return "blocked"
    for n in open_blocked:  # jiný cíl / důvod → starší oznámení nahradit
        n.resolved = True
    title, message = REASONS[status["reason"]]
    stamp = now or utc_now()
    db.add(Notification(area="system", title=title, message=f"{message} Verze {status['target'][:7]}.",
                        severity="warning", read=False, created_at=stamp, notification_type="ops_alert",
                        source_type=BLOCKED_SOURCE, source_id=None, dedupe_key=key, last_triggered_at=stamp,
                        resolved=False, action_url=None))
    db.flush()
    return "blocked"
