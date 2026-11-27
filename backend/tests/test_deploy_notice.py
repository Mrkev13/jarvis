"""MRK-151: oznámení „Hub aktualizován“ – jednou na commit, starší se vyřeší, bez APP_COMMIT nic, jde do push."""
import os
import sys
from unittest.mock import patch

TESTS_DIR = os.path.dirname(__file__)
BACKEND_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import delivery_service  # noqa: E402
import deploy_notice  # noqa: E402
from database import Base  # noqa: E402
from models import Notification  # noqa: E402

A = "a" * 40
B = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def Session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def notes(Session):
    db = Session()
    try:
        return [(n.dedupe_key, n.resolved, n.title, n.message, n.notification_type) for n in db.query(Notification)]
    finally:
        db.close()


def test_once_per_commit_and_older_resolved(Session):
    with patch.dict(os.environ, {"APP_COMMIT": A}):
        deploy_notice.announce_from_env(Session)
        deploy_notice.announce_from_env(Session)  # restart na stejném commitu
    assert notes(Session) == [(f"deploy:{A}", False, "Hub aktualizován", "Běží nová verze aaaaaaa.", "ops_alert")]
    with patch.dict(os.environ, {"APP_COMMIT": B}):
        deploy_notice.announce_from_env(Session)
    assert [(k, r) for k, r, *_ in notes(Session)] == [(f"deploy:{A}", True), (f"deploy:{B}", False)]
    assert "ops_alert" in delivery_service.deliverable_types(), "jde i do Web Push (OPS_ALERT_PUSH)"


@pytest.mark.parametrize("value", ["", "abc", "Z" * 40, "deadbeef"])
def test_without_valid_commit_nothing(Session, value):
    with patch.dict(os.environ, {"APP_COMMIT": value}):
        deploy_notice.announce_from_env(Session)
    assert notes(Session) == []


def test_failure_never_breaks_startup(Session):
    with patch.dict(os.environ, {"APP_COMMIT": A}), patch.object(deploy_notice, "announce_deploy", side_effect=RuntimeError):
        deploy_notice.announce_from_env(Session)  # nevyhodí


# ---------- zastavené nasazení ----------

import json  # noqa: E402
from datetime import datetime  # noqa: E402

NOW = datetime(2026, 11, 27, 12, 0)


def write_status(tmp_path, **data):
    path = tmp_path / "updater-status.json"
    path.write_text(json.dumps({"at": "2026-11-27T11:50:00Z", "target": B, **data}))
    return str(path)


def check(Session, path, now=NOW):
    db = Session()
    try:
        out = deploy_notice.check_updater_status(db, path, now)
        db.commit()
        return out
    finally:
        db.close()


def test_blocked_on_migration_once_then_resolved(Session, tmp_path):
    path = write_status(tmp_path, state="blocked", reason="MIGRATION_HEAD_CHANGED")
    assert check(Session, path) == "blocked"
    assert check(Session, path) == "blocked"  # další hodinový běh – žádné druhé oznámení
    rows = notes(Session)
    assert len(rows) == 1 and rows[0][2] == "Nasazení čeká na migraci" and rows[0][4] == "ops_alert"
    assert "deploy-migration-v3.sh" in rows[0][3] and B[:7] in rows[0][3]
    path = write_status(tmp_path, state="ok")
    assert check(Session, path) == "resolved"
    assert notes(Session)[0][1] is True


def test_unknown_reason_is_generic_and_nothing_raw_leaks(Session, tmp_path):
    path = write_status(tmp_path, state="blocked", reason="secret-host.ts.net: boom")
    assert check(Session, path) == "blocked"
    (key, _, title, message, _) = notes(Session)[0]
    assert title == "Nasazení se nepovedlo" and "ts.net" not in message + key


@pytest.mark.parametrize("content", [
    None,                                                              # soubor chybí
    "{not json",
    json.dumps({"at": "2026-11-27T08:00:00Z", "target": B, "state": "blocked", "reason": "MIGRATION_HEAD_CHANGED"}),  # starý
    json.dumps({"at": "2026-11-27T11:50:00Z", "target": "abc", "state": "blocked"}),
    json.dumps({"at": "2026-11-27T11:50:00Z", "target": B, "state": "weird"}),
    json.dumps({"at": "2026-11-27T11:50:00Z", "target": B, "state": "waiting"}),  # CI nové verze ještě běží
    "x" * 5000,
])
def test_missing_stale_or_invalid_status_is_ignored(Session, tmp_path, content):
    path = tmp_path / "updater-status.json"
    if content is not None:
        path.write_text(content)
    assert check(Session, str(path)) == "none"
    assert notes(Session) == []
