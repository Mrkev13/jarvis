"""MRK-151: deploy/v3/lib/updater-status-v3.sh – stav posledního běhu updateru pro Hub.

Falešný `journalctl` na PATH vrací log jednoho běhu; ověřuje se zapsaný JSON (stav, důvod, cíl), že nic neunikne
z logu do souboru a že skript nikdy neselže. Žádná síť, žádný systemd.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "v3" / "lib" / "updater-status-v3.sh"
DROPIN = ROOT / "deploy" / "v3" / "systemd" / "standa-hub-auto-update.service.d" / "30-status.conf"
INV = "0123456789abcdef0123456789abcdef"
TARGET = "a" * 40

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def run(tmp_path, log, *, result="success", inv=INV, journal_fails=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "log.txt").write_text(log)
    fake = bin_dir / "journalctl"
    fake.write_text("#!/usr/bin/env bash\n"
                    + ("exit 1\n" if journal_fails else
                       f'[[ "$*" == *"_SYSTEMD_INVOCATION_ID={INV}"* ]] && cat "{tmp_path}/log.txt"\n'))
    fake.chmod(0o755)
    out = tmp_path / "ops"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "UPDATER_STATUS_DIR": str(out),
           "INVOCATION_ID": inv, "SERVICE_RESULT": result}
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    path = out / "updater-status.json"
    return json.loads(path.read_text()) if path.exists() else None


def log(*lines):
    return "\n".join(["=== FETCH PRODUCTION BRANCH ===", "Current: " + "b" * 40, f"Target:  {TARGET}", *lines]) + "\n"


@pytest.mark.parametrize("lines,result,state,reason", [
    (["AUTO_UPDATE_DEPLOYED"], "success", "ok", ""),
    (["NO_UPDATE_NEEDED"], "success", "ok", ""),
    (["MIGRATION_HEAD_CHANGED: MANUAL_REVIEW_REQUIRED"], "exit-code", "blocked", "MIGRATION_HEAD_CHANGED"),
    (["CI_NOT_APPROVED: in_progress"], "exit-code", "waiting", ""),
    (["CI_NOT_FOUND"], "exit-code", "waiting", ""),
    (["BACKUP_TOO_OLD"], "exit-code", "blocked", "BACKUP_NOT_FRESH"),
    (["FRONTEND_UNHEALTHY", "ROLLBACK_VERIFIED"], "exit-code", "blocked", "DEPLOY_FAILED"),
])
def test_state_from_this_run(tmp_path, lines, result, state, reason):
    data = run(tmp_path, log(*lines), result=result)
    assert (data["state"], data["reason"], data["target"]) == (state, reason, TARGET)
    assert data["at"].endswith("Z")
    assert set(data) == {"at", "state", "reason", "target"}


def test_nothing_from_the_log_leaks_into_the_file(tmp_path):
    data = run(tmp_path, log("https://<tailnet-host>.ts.net secret=abc DEPLOY_ERROR"), result="exit-code")
    text = json.dumps(data)
    assert "ts.net" not in text and "secret" not in text and data["reason"] == "DEPLOY_FAILED"


@pytest.mark.parametrize("kwargs,content", [
    ({"inv": "not-an-id"}, log("AUTO_UPDATE_DEPLOYED")),
    ({}, "=== FETCH PRODUCTION BRANCH ===\nINVALID_TARGET_SHA\n"),   # cíl nezjištěn
    ({"journal_fails": True}, log("AUTO_UPDATE_DEPLOYED")),
])
def test_writes_nothing_and_never_fails(tmp_path, kwargs, content):
    assert run(tmp_path, content, **kwargs) is None


def test_file_is_world_readable_and_replaced_atomically(tmp_path):
    run(tmp_path, log("NO_UPDATE_NEEDED"))
    data = run(tmp_path, log("MIGRATION_HEAD_CHANGED: MANUAL_REVIEW_REQUIRED"), result="exit-code")
    assert data["state"] == "blocked"
    files = sorted(p.name for p in (tmp_path / "ops").iterdir())
    assert files == ["updater-status.json"], "žádné dočasné soubory"
    assert oct((tmp_path / "ops" / "updater-status.json").stat().st_mode & 0o777) == "0o644"


def test_systemd_dropin_runs_it_after_every_run():
    text = DROPIN.read_text()
    assert "ExecStopPost=/usr/local/lib/standa-hub/updater-status-v3.sh" in text
