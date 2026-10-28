"""MRK-78: the Control Center layout is stored on the server, so a change on the PC applies on the phone too."""
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import ActivityLog, UiPreference
from module_registry import ModuleAccess

LAYOUT = {"version": 1, "widgets": [{"id": "burning", "visible": True, "order": 10, "size": "full"},
                                    {"id": "key_metrics", "visible": False, "order": 20, "size": "full"}]}


@pytest.fixture
def client(monkeypatch):
    import database
    import main
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", session)
    with patch.object(main, "auth_enabled", return_value=False), \
            patch.object(main, "current_access", return_value=ModuleAccess({})):
        c = TestClient(main.app)
        c.db = session
        yield c
        c.close()
    engine.dispose()


def test_round_trip_across_devices(client):
    assert client.get("/preferences/dashboard_layout").json()["value"] is None
    saved = client.put("/preferences/dashboard_layout", json={"value": LAYOUT})
    assert saved.status_code == 200 and saved.json()["value"] == LAYOUT
    # „another device" = a fresh GET
    assert client.get("/preferences/dashboard_layout").json()["value"] == LAYOUT
    db = client.db()
    try:
        assert db.query(ActivityLog).filter_by(entity_type="UiPreference").count() == 1
    finally:
        db.close()


def test_unchanged_save_writes_nothing_and_reset_removes_the_row(client):
    client.put("/preferences/dashboard_layout", json={"value": LAYOUT})
    client.put("/preferences/dashboard_layout", json={"value": LAYOUT})
    assert client.delete("/preferences/dashboard_layout").json()["value"] is None
    db = client.db()
    try:
        assert db.query(UiPreference).count() == 0
        assert db.query(ActivityLog).filter_by(entity_type="UiPreference").count() == 2  # save + reset
    finally:
        db.close()


@pytest.mark.parametrize("value", [
    {"widgets": []},                                                   # no version
    {"version": 1, "widgets": "x"},
    {"version": 1, "widgets": [{"id": "a", "visible": "yes", "order": 1, "size": "full"}]},
    {"version": 1, "widgets": [{"id": "a", "visible": True, "order": True, "size": "full"}]},
    {"version": 1, "widgets": [{"id": "a", "visible": True, "order": 1, "size": "huge"}]},
    {"version": 1, "widgets": [{"id": "", "visible": True, "order": 1, "size": "full"}]},
    {"version": 1, "widgets": [{"id": f"w{i}", "visible": True, "order": i, "size": "full"} for i in range(65)]},
])
def test_invalid_layouts_are_refused(client, value):
    assert client.put("/preferences/dashboard_layout", json={"value": value}).status_code == 422
    assert client.get("/preferences/dashboard_layout").json()["value"] is None


def test_extra_fields_are_dropped_and_unknown_keys_refused(client):
    noisy = {"version": 1, "widgets": [{"id": "goals", "visible": True, "order": 10, "size": "small", "note": "x" * 50}],
             "secret": "canary"}
    stored = client.put("/preferences/dashboard_layout", json={"value": noisy}).json()["value"]
    assert stored == {"version": 1, "widgets": [{"id": "goals", "visible": True, "order": 10, "size": "small"}]}
    assert "canary" not in json.dumps(stored)
    assert client.get("/preferences/theme").status_code == 404
    assert client.put("/preferences/theme", json={"value": LAYOUT}).status_code == 404


def test_requires_session():
    import main
    with patch.object(main, "auth_enabled", return_value=True), patch.object(main, "validate_session_token", return_value=None):
        c = TestClient(main.app)
        assert c.get("/preferences/dashboard_layout").status_code == 401
        assert c.put("/preferences/dashboard_layout", json={"value": LAYOUT}).status_code == 401
        c.close()


def test_quick_successive_edits_keep_the_last_value_and_one_activity_row(client):
    other = {"version": 2, "widgets": [{"id": "day", "visible": True, "order": 10, "size": "medium"}]}
    assert client.put("/preferences/dashboard_layout", json={"value": LAYOUT}).status_code == 200
    assert client.put("/preferences/dashboard_layout", json={"value": other}).status_code == 200
    assert client.get("/preferences/dashboard_layout").json()["value"] == other
    db = client.db()
    try:
        assert db.query(ActivityLog).filter_by(entity_type="UiPreference").count() == 1, "jedna Aktivita za minutu"
    finally:
        db.close()
