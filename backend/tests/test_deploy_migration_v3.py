"""MRK-114: controlled migration deployment (deploy/v3/lib/deploy-migration-v3.sh) in isolation.

Builds on the v3 world of test_deploy_v3.py (real updater, journal, release and backup checks, fake docker / curl / gh,
real git with a local origin). The fake docker models the production database revision, throwaway PostgreSQL copies
restored from a gzip dump, rehearsal app containers and `alembic upgrade head` (see deploy_v3_fakes/docker).

Standa's conditions (MRK-114): fresh backup + a restore of it; static check of the migration is not enough - old AND
new application against a migrated copy; recorded phases, recovery reads the production revision after an interrupted
migration; never a database downgrade; an app rollback counts only after the old application passed its compatibility
check; a migration release is never deployed by the automatic updater, not even with a database migrated in advance.
"""
import gzip
import hashlib
import json
import shutil
import subprocess

import pytest

from tests.test_deploy_v3 import V3, World, out

OLD, NEW = '0028_school_progress', '0029_attendance_schedule'
MIGRATION_0028 = '''"""0028"""
revision = "0028_school_progress"
down_revision = "0027_ui_preferences"


def upgrade() -> None:
    op.create_table("school_attendance")


def downgrade() -> None:
    op.drop_table("school_attendance")
'''
MIGRATION_0029 = '''"""0029"""
from alembic import op
import sqlalchemy as sa

revision = "0029_attendance_schedule"
down_revision = "0028_school_progress"


def upgrade() -> None:
    with op.batch_alter_table("subjects") as batch:
        batch.add_column(sa.Column("attendance_every", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("attendance_anchor", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subjects") as batch:
        batch.drop_column("attendance_anchor")
        batch.drop_column("attendance_every")
'''
FAKE_BACKUP = '''#!/usr/bin/env python3
"""Fake backup.sh: gzip dump of the production database revision + success manifest."""
import gzip, hashlib, json, os, time
from pathlib import Path
fake, root = Path(os.environ["FAKE_DIR"]), Path(os.environ["DEPLOY_BACKUP_ROOT"])
rev = json.loads((fake / "state.json").read_text())["prod_db"]
with open(fake / "calls.log", "a") as f:
    f.write(f"backup {rev}\\n")
name = f"db_{time.time_ns()}.sql.gz"
data = gzip.compress(f"-- dump\\nREVISION={rev}\\n".encode())
(root / name).write_bytes(data)
(root / "runs" / f"backup_{time.time_ns()}.json").write_text(json.dumps({"status": "success", "database": {
    "filename": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}}))
'''


class MigWorld(World):
    def __init__(self, tmp):
        super().__init__(tmp)
        self.migration = tmp / 'deploy-migration-v3.sh'
        shutil.copy(V3 / 'lib' / 'deploy-migration-v3.sh', self.migration)
        self.migration.chmod(0o755)
        backup = tmp / 'backup-cmd'
        backup.write_text(FAKE_BACKUP)
        backup.chmod(0o755)
        self.env['DEPLOY_BACKUP_CMD'] = str(backup)

    def deploy_running(self, sha):
        super().deploy_running(sha)
        self.mutate(lambda s: s.update(prod_db=OLD))

    def fresh_backup(self):
        data = gzip.compress(f'-- dump\nREVISION={OLD}\n'.encode())
        (self.backups / 'db.sql.gz').write_bytes(data)
        (self.backups / 'runs' / 'backup_1.json').write_text(json.dumps({'status': 'success', 'database': {
            'filename': 'db.sql.gz', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}}))

    def migration_release(self, upgrade=MIGRATION_0029, old_compatible=True):
        """Commit B with migration 0029; the updater builds its images + provenance and stops (head changed)."""
        versions = self.work / 'backend' / 'alembic' / 'versions'
        versions.mkdir(parents=True, exist_ok=True)
        (versions / '0028_school_progress.py').write_text(MIGRATION_0028)
        (versions / '0029_attendance_schedule.py').write_text(upgrade)
        b = self.commit('B with migration 0029', head=NEW)
        self.ci_success(b)
        r = self.update('--check')
        assert r.returncode != 0 and 'MIGRATION_HEAD_CHANGED' in out(r), out(r)
        assert (self.state / 'provenance' / f'{b}.json').exists()
        if old_compatible:  # additive migration: the old code also works on the new schema
            self.set_compat(self.running()[0], [OLD, NEW])
        return b

    def set_compat(self, image, revisions):
        self.mutate(lambda s: s['meta'][image].update(compat=revisions))

    def mig(self, mode, sha, **extra):
        return self._locked(str(self.migration), mode, sha, extra=extra)

    def prod_db(self):
        return self.state_json()['prod_db']

    def mjournal(self, sha):
        return json.loads((self.state / f'migration-v3-{sha}' / 'journal.json').read_text())

    def archived(self, sha):
        archive = self.state / 'archive'
        return sorted(p for p in archive.glob(f'migration-v3-{sha}.*')) if archive.exists() else []

    def rehearsal_leftovers(self):
        s = self.state_json()
        return list(s.get('apps', {})) + list(s.get('copies', {})) + list(s.get('networks', []))


@pytest.fixture
def m(tmp_path):
    return MigWorld(tmp_path)


# ---------- happy path ----------

def test_check_rehearses_on_a_copy_and_changes_nothing(m):
    b = m.migration_release()
    before = m.running()
    r = m.mig('--check', b)
    assert r.returncode == 0, out(r)
    for marker in ('MIGRATION_OPS_ADDITIVE', 'PRODUCTION_DATABASE_AT_OLD_HEAD', 'REHEARSAL_RESTORE_OK',
                   'REHEARSAL_OLD_APP_BASELINE_OK', 'REHEARSAL_MIGRATION_OK', 'REHEARSAL_NEW_APP_OK',
                   'REHEARSAL_OLD_APP_COMPATIBLE', 'MIGRATION_PREFLIGHT_OK', 'NO_PRODUCTION_CHANGES'):
        assert marker in r.stdout, marker
    assert m.prod_db() == OLD and m.running() == before
    assert m.rehearsal_leftovers() == [], 'throwaway database, apps and network removed'
    assert not (m.state / f'migration-v3-{b}').exists()
    calls = (m.fake / 'calls.log').read_text()
    assert 'migrate copy' in calls and 'migrate prod' not in calls
    assert 'network create --internal' in calls and '--tmpfs /var/lib/postgresql' in calls


def test_apply_backs_up_rehearses_migrates_and_deploys(m):
    b = m.migration_release()
    r = m.mig('--apply', b)
    assert r.returncode == 0, out(r)
    assert 'MIGRATION_DEPLOYMENT_OK' in r.stdout
    assert m.prod_db() == NEW and m.running_commit() == b
    j = m.mjournal(b)
    assert j['state'] == 'deployed' and (j['old_head'], j['new_head']) == (OLD, NEW)
    assert [h['state'] for h in j['history']] == ['prepared', 'rehearsed', 'db_migrating', 'db_migrated', 'deploying',
                                                  'verifying', 'deployed']
    calls = (m.fake / 'calls.log').read_text().splitlines()
    first = lambda prefix: next(i for i, c in enumerate(calls) if c.startswith(prefix))  # noqa: E731
    assert first('backup') < first('migrate copy') < first('migrate prod') < first('up backend'), 'order'
    assert j['backup_dump'].startswith('db_'), 'rehearsal on the backup taken right before'
    # the automatic updater is happy afterwards (database and code agree), nothing pending
    again = m.update()
    assert again.returncode == 0 and 'NO_UPDATE_NEEDED' in again.stdout, out(again)


# ---------- the automatic updater never deploys a migration release ----------

def test_updater_refuses_a_migration_release_even_with_the_database_migrated_in_advance(m):
    b = m.migration_release()
    m.mutate(lambda s: s.update(prod_db=NEW))  # someone ran the migration by hand
    r = m.update()
    assert r.returncode != 0 and m.running_commit() == m.a, out(r)
    assert 'BACKEND_HEALTH_FAILED' in out(r) or 'MIGRATION_HEAD_CHANGED' in out(r)
    # and the controlled procedure does not accept an unexplained migrated database either
    r = m.mig('--check', b)
    assert r.returncode != 0 and m.running_commit() == m.a


def test_unfinished_migration_blocks_the_updater(m):
    b = m.migration_release()
    m.inject(kill_before_migrate=['prod'])
    m.mig('--apply', b)
    assert m.mjournal(b)['state'] == 'db_migrating'
    r = m.update()
    assert r.returncode != 0 and 'PENDING_MIGRATION' in out(r)


# ---------- checks that stop before any production change ----------

def test_non_additive_migration_is_refused(m):
    b = m.migration_release(upgrade=MIGRATION_0029.replace(
        'batch.add_column(sa.Column("attendance_anchor", sa.Date(), nullable=True))', 'batch.drop_column("credits")'))
    r = m.mig('--apply', b)
    assert r.returncode != 0 and 'MIGRATION_OPS_NOT_ADDITIVE' in out(r)
    assert m.prod_db() == OLD and not (m.state / f'migration-v3-{b}').exists()


def test_not_null_column_without_default_is_refused(m):
    b = m.migration_release(upgrade=MIGRATION_0029.replace('sa.Date(), nullable=True', 'sa.Date(), nullable=False'))
    assert 'add_column without nullable=True' in out(m.mig('--check', b))


def test_old_app_incompatible_with_migrated_copy_stops_check_and_apply(m):
    b = m.migration_release(old_compatible=False)  # additive on paper, but the old code breaks on the new schema
    before = m.running()
    chk = m.mig('--check', b)
    assert chk.returncode != 0
    assert 'REHEARSAL_APP_UNHEALTHY' in out(chk) or 'REHEARSAL_ORM_SMOKE_FAILED' in out(chk), out(chk)
    r = m.mig('--apply', b)
    assert r.returncode != 0 and 'MIGRATION_ABORTED_NO_PRODUCTION_CHANGE' in out(r), out(r)
    assert m.prod_db() == OLD and m.running() == before
    assert len(m.archived(b)) == 1 and m.rehearsal_leftovers() == []
    assert 'migrate prod' not in (m.fake / 'calls.log').read_text()


def test_new_app_unhealthy_in_rehearsal_stops_before_production(m):
    b = m.migration_release()
    m.mutate(lambda s: s['unhealthy'].append(s['tags'][f'standa-hub-backend:{b}']))
    r = m.mig('--apply', b)
    assert r.returncode != 0 and m.prod_db() == OLD
    assert 'REHEARSAL_APP_UNHEALTHY' in out(r)


def test_missing_provenance_is_refused(m):
    b = m.migration_release()
    (m.state / 'provenance' / f'{b}.json').unlink()
    assert 'TARGET_IMAGE_PROVENANCE_MISSING' in out(m.mig('--check', b))


def test_not_a_migration_release_goes_to_the_updater(m):
    b = m.commit('B without migration')
    m.ci_success(b)
    m.update('--check')
    assert 'NOT_A_MIGRATION_RELEASE' in out(m.mig('--check', b))


# ---------- failures and recovery on production ----------

def test_failed_production_migration_aborts_with_database_unchanged(m):
    b = m.migration_release()
    before = m.running()
    m.inject(fail_migrate=['prod'])
    r = m.mig('--apply', b)
    assert r.returncode != 0 and 'MIGRATION_ABORTED_NO_PRODUCTION_CHANGE' in out(r), out(r)
    assert m.prod_db() == OLD and m.running() == before and len(m.archived(b)) == 1
    retry = m.mig('--apply', b)
    assert retry.returncode == 0 and m.prod_db() == NEW, out(retry)


def test_power_loss_before_the_migration_applied_recovers_as_aborted(m):
    b = m.migration_release()
    m.inject(kill_before_migrate=['prod'])
    m.mig('--apply', b)
    assert m.mjournal(b)['state'] == 'db_migrating' and m.prod_db() == OLD
    rec = m.mig('--recover', b)
    assert rec.returncode == 0 and 'MIGRATION_ABORTED_NO_PRODUCTION_CHANGE' in rec.stdout, out(rec)
    assert m.running_commit() == m.a and m.mig('--apply', b).returncode == 0 and m.prod_db() == NEW


def test_power_loss_after_the_migration_applied_rolls_forward(m):
    b = m.migration_release()
    m.inject(kill_after_migrate=['prod'])
    m.mig('--apply', b)
    j = m.mjournal(b)
    assert j['state'] == 'db_migrating' and m.prod_db() == NEW, 'database changed, journal not yet'
    assert m.running_commit() == m.a, 'old app keeps running (rehearsed as compatible)'
    rec = m.mig('--recover', b)
    assert rec.returncode == 0 and 'MIGRATION_DEPLOYMENT_OK' in rec.stdout, out(rec)
    states = [h['state'] for h in m.mjournal(b)['history']]
    assert states == ['prepared', 'rehearsed', 'db_migrating', 'db_migrated', 'deploying', 'verifying', 'deployed']
    assert 'migrate prod' not in rec.stdout and (m.fake / 'calls.log').read_text().count('migrate prod') == 1, \
        'roll forward without a second migration'
    assert m.running_commit() == b and m.mjournal(b)['state'] == 'deployed'


def test_unhealthy_new_app_rolls_back_the_app_only_after_compat_check(m):
    b = m.migration_release()
    old = m.running()
    m.mutate(lambda s: s['unhealthy'].append(s['tags'][f'standa-hub-frontend:{b}']))  # new frontend broken
    r = m.mig('--apply', b)
    assert r.returncode != 0
    assert 'OLD_APP_COMPATIBLE_WITH_MIGRATED_DATABASE' in out(r) and 'APP_ROLLED_BACK_DATABASE_STAYS_MIGRATED' in out(r)
    assert m.mjournal(b)['state'] == 'rolled_back_app'
    assert m.running() == old and m.prod_db() == NEW, 'database never downgraded'
    assert not any(c.startswith('migrate') and 'downgrade' in c for c in (m.fake / 'calls.log').read_text().splitlines())


def test_app_rollback_without_a_compatible_old_app_is_not_success(m):
    """'migrations: mismatch' alone is never a successful rollback (Standa's condition)."""
    b = m.migration_release()
    m.inject(kill_on_up=['backend'])
    m.mig('--apply', b)
    assert m.mjournal(b)['state'] == 'deploying' and m.prod_db() == NEW
    m.set_compat(m.running()[0], [OLD])  # the old code turns out to break on the migrated production database
    rec = m.mig('--recover', b)
    assert rec.returncode != 0 and 'APP_ROLLBACK_NOT_VERIFIED' in out(rec)
    assert m.mjournal(b)['state'] == 'app_rollback_required' and m.prod_db() == NEW
    assert 'PENDING_MIGRATION' in out(m.update()), 'blocks automatic updates until resolved by hand'


def test_stale_staging_is_removed_and_writable_script_refused(m):
    b = m.migration_release()
    stale = m.state / f'.staging-migration-v3-{b}.XXXX'
    stale.mkdir(mode=0o700)
    (stale / 'backend.json').write_text('{"secret": "x"}')
    r = m.mig('--apply', b)
    assert r.returncode == 0 and 'STALE_STAGING_REMOVED' in r.stdout and not stale.exists(), out(r)
    m.migration.chmod(0o775)
    assert 'UNTRUSTED_PATH' in out(m.mig('--check', b))


# ---------- helpers ----------

def test_migration_journal_transitions(m, tmp_path):
    j = tmp_path / 'j.json'
    journal = str(m.trusted / 'migration-journal.py')

    def go(state):
        return subprocess.run(['python3', '-I', journal, str(j), state], capture_output=True, text=True)
    j.write_text(json.dumps({'state': 'db_migrating'}))
    assert 'INVALID_TRANSITION' in go('deploying').stderr, 'migrating -> deploying only via verified db_migrated'
    assert go('db_migrated').returncode == 0
    assert 'INVALID_TRANSITION' in go('aborted').stderr, 'a migrated database is never "aborted"'
    j.write_text(json.dumps({'state': 'rolled_back_app'}))
    assert 'INVALID_TRANSITION' in go('db_migrating').stderr, 'terminal'


@pytest.mark.parametrize('body, ok', [
    ('op.create_table("x", sa.Column("id", sa.Integer(), nullable=False))', True),
    ('op.create_index(op.f("ix_x"), "x", ["id"])', True),
    ('op.add_column("t", sa.Column("c", sa.Text(), server_default="a", nullable=False))', True),
    ('op.add_column("t", sa.Column("c", sa.Text()))', False),
    ('op.alter_column("t", "c", nullable=False)', False),
    ('op.execute("UPDATE t SET c = 1")', False),
    ('op.drop_table("t")', False),
    ('op.get_bind().execute(sa.text("select 1"))', False),
])
def test_check_migration_whitelist(m, tmp_path, body, ok):
    v = tmp_path / 'versions'
    v.mkdir()
    (v / 'a.py').write_text('revision = "a"\ndown_revision = "z"\n\ndef upgrade() -> None:\n    pass\n')
    (v / 'b.py').write_text(f'revision = "b"\ndown_revision = "a"\n\ndef upgrade() -> None:\n    {body}\n\n'
                            'def downgrade() -> None:\n    op.drop_table("x")\n')
    r = subprocess.run(['python3', '-I', str(m.trusted / 'check-migration.py'), str(v), 'a', 'b'],
                       capture_output=True, text=True)
    assert (r.returncode == 0) == ok, r.stdout


def test_check_migration_refuses_merge_and_broken_chains(m, tmp_path):
    v = tmp_path / 'versions'
    v.mkdir()
    (v / 'm.py').write_text('revision = "m"\ndown_revision = ("a", "x")\n\ndef upgrade() -> None:\n    pass\n')
    run = lambda new: subprocess.run(['python3', '-I', str(m.trusted / 'check-migration.py'), str(v), 'a', new],  # noqa: E731
                                     capture_output=True, text=True).stdout
    assert 'merge or root migration' in run('m')
    assert 'not found' in run('missing')


# ---------- Codex review (BLOCK on a8d3e7e) regressions ----------

def _migration_file(tmp_path, upgrade_body, module_extra=''):
    v = tmp_path / 'versions'
    v.mkdir(exist_ok=True)
    (v / 'a.py').write_text('revision = "a"\ndown_revision = "z"\n\ndef upgrade() -> None:\n    pass\n')
    (v / 'b.py').write_text(f'"""b"""\nfrom alembic import op\nimport sqlalchemy as sa\n{module_extra}\n'
                            f'revision = "b"\ndown_revision = "a"\n\n\ndef upgrade() -> None:\n{upgrade_body}\n\n\n'
                            'def downgrade() -> None:\n    op.drop_table("x")\n')
    return v


@pytest.mark.parametrize('upgrade_body, module_extra', [
    ('    _helper()', 'def _helper():\n    op.drop_table("subjects")\n'),          # helper hides a drop
    ('    o = op\n    o.drop_table("subjects")', ''),                               # alias
    ('    getattr(op, "drop_table")("subjects")', ''),                              # dynamic attribute
    ('    exec("op.drop_table(\'subjects\')")', ''),                                # arbitrary Python
    ('    pass', 'import os\nos.system("true")\n'),                                 # module-level code
    ('    with op.batch_alter_table("t") as b:\n        b.drop_column("c")', ''),    # drop inside batch
    ('    with op.batch_alter_table("t") as op:\n        op.drop_table("c")', ''),    # alias shadows op
    ('    op.add_column("t", sa.Column("c", sa.Text(), server_default=sa.text("1; DROP TABLE t")))', ''),
    ('    op.add_column("t", sa.Column("c", sa.Text(), nullable=(lambda: True)()))', ''),
    ('    for _ in range(1):\n        op.create_table("x")', ''),                  # control flow
    ('    op.create_table("x", *cols)', 'cols = []\n'),                             # names / starred
])
def test_check_migration_bypasses_are_refused(m, tmp_path, upgrade_body, module_extra):
    v = _migration_file(tmp_path, upgrade_body, module_extra)
    r = subprocess.run(['python3', '-I', str(m.trusted / 'check-migration.py'), str(v), 'a', 'b'],
                       capture_output=True, text=True)
    assert r.returncode == 1 and 'MIGRATION_OPS_NOT_ADDITIVE' in r.stdout, (upgrade_body, r.stdout)


def test_check_migration_accepts_the_real_additive_shapes(m, tmp_path):
    v = _migration_file(tmp_path, '    with op.batch_alter_table("subjects") as batch:\n'
                                  '        batch.add_column(sa.Column("e", sa.Integer(), nullable=True))\n'
                                  '    op.create_table("t", sa.Column("id", sa.Integer(), nullable=False),\n'
                                  '                    sa.PrimaryKeyConstraint("id"))\n'
                                  '    op.create_index(op.f("ix_t_id"), "t", ["id"], unique=False)')
    r = subprocess.run(['python3', '-I', str(m.trusted / 'check-migration.py'), str(v), 'a', 'b'],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize('how', ['writable', 'symlink', 'writable_dir'])
def test_backup_command_must_be_trusted(m, how):
    b = m.migration_release()
    cmd = m.tmp / 'backup-cmd'
    if how == 'writable':
        cmd.chmod(0o777)
    elif how == 'symlink':
        real = m.tmp / 'backup-real'
        cmd.rename(real)
        cmd.symlink_to(real)
    else:
        sub = m.tmp / 'open'
        sub.mkdir(mode=0o777)
        sub.chmod(0o777)
        moved = sub / 'backup-cmd'
        cmd.rename(moved)
        m.env['DEPLOY_BACKUP_CMD'] = str(moved)
    r = m.mig('--apply', b)
    assert r.returncode != 0 and 'UNTRUSTED_PATH' in out(r)
    assert 'backup ' not in ((m.fake / 'calls.log').read_text() if (m.fake / 'calls.log').exists() else '')


def test_power_loss_after_aborted_is_archived_by_recover_and_apply(m):
    b = m.migration_release(old_compatible=False)
    real = m.trusted / 'migration-journal.real.py'
    shutil.move(m.trusted / 'migration-journal.py', real)
    (m.trusted / 'migration-journal.py').write_text(f'''import os, signal, subprocess, sys
rc = subprocess.call([sys.executable, "-I", {str(real)!r}, *sys.argv[1:]])
if rc == 0 and sys.argv[2] == "aborted":
    os.kill(os.getppid(), signal.SIGKILL)
sys.exit(rc)
''')
    (m.trusted / 'migration-journal.py').chmod(0o644)
    m.mig('--apply', b)
    shutil.move(real, m.trusted / 'migration-journal.py')
    (m.trusted / 'migration-journal.py').chmod(0o644)
    assert m.mjournal(b)['state'] == 'aborted' and m.archived(b) == [], 'crash window: aborted, not archived'
    assert 'ABORTED_MIGRATION_WILL_BE_ARCHIVED' in m.mig('--check', b).stdout
    rec = m.mig('--recover', b)
    assert rec.returncode == 0 and 'MIGRATION_TRANSACTION_ARCHIVED' in rec.stdout, out(rec)
    assert len(m.archived(b)) == 1 and not (m.state / f'migration-v3-{b}').exists()
    m.set_compat(m.running()[0], [OLD, NEW])
    assert m.mig('--apply', b).returncode == 0 and m.prod_db() == NEW


def test_rollback_refuses_when_managed_config_no_longer_matches_snapshot(m):
    b = m.migration_release()
    m.inject(kill_on_up=['backend'])
    m.mig('--apply', b)
    snap = m.state / f'migration-v3-{b}' / 'backend.json'
    data = json.loads(snap.read_text())
    data['services']['backend']['environment']['APP_COMMIT'] = '0' * 40
    snap.write_text(json.dumps(data))
    rec = m.mig('--recover', b)
    assert rec.returncode != 0 and 'MANAGED_CONFIG_CHANGED_SINCE_SNAPSHOT' in out(rec)
    assert m.mjournal(b)['state'] == 'app_rollback_required'


def test_rehearsal_uses_the_immutable_postgres_image_id(m):
    b = m.migration_release()
    assert m.mig('--check', b).returncode == 0
    runs = [c for c in (m.fake / 'calls.log').read_text().splitlines() if c.startswith('run -d') and 'POSTGRES_DB' in c]
    assert runs and all(('sha256:' + '5' * 64) in c and 'postgres:18.6' not in c for c in runs)
