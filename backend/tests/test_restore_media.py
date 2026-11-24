"""MRK-101 review: deploy/scripts/restore-media.py restores into a fresh scratch directory (any absolute path such as
/tmp/... must work) and refuses "/", the production media/backup directories, anything inside them and their
ancestors. End to end with a small valid backup (run manifest -> media manifest -> archived files)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy' / 'scripts' / 'restore-media.py'
pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='POSIX paths')


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def backup(tmp_path):
    root = tmp_path / 'backups'
    files = {'school/notes.pdf': b'%PDF-1.4 notes', 'wot/replay.wotreplay': b'replay-bytes', 'a.txt': b'hello'}
    archive = root / 'media' / 'run1'
    items = []
    for rel, data in files.items():
        target = archive / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        items.append({'archive_path': f'media/run1/{rel}', 'relative_path': rel, 'size': len(data), 'sha256': sha(data)})
    manifest = root / 'media' / 'run1.json'
    manifest.write_text(json.dumps({'files': items, 'file_count': len(items),
                                    'total_bytes': sum(i['size'] for i in items)}))
    run = root / 'runs' / 'backup_1.json'
    run.parent.mkdir(parents=True)
    run.write_text(json.dumps({'status': 'success', 'media': {'manifest': 'media/run1.json',
                                                               'manifest_sha256': sha(manifest.read_bytes())}}))
    return root, manifest, run, files


def restore(backup, destination):
    root, manifest, run, _ = backup
    return subprocess.run([sys.executable, '-I', str(SCRIPT), '--backup-root', str(root), '--manifest', str(manifest),
                           '--run-manifest', str(run), '--destination', str(destination)],
                          capture_output=True, text=True)


def test_restores_into_a_fresh_absolute_scratch_directory(backup, tmp_path):
    destination = tmp_path / 'jarvis-mrk101-media-restore'   # absolute, like the documented /tmp/... drill
    assert destination.is_absolute()
    r = restore(backup, destination)
    assert r.returncode == 0, r.stderr
    for rel, data in backup[3].items():
        assert (destination / rel).read_bytes() == data


@pytest.mark.parametrize('destination', [
    '/',
    '/srv/standa-hub-data/media',
    '/srv/standa-hub-data/media/restore',
    '/srv/standa-hub-data/backups/restore',
    '/srv/standa-hub-data',            # ancestor of the production directories
    '/srv',
])
def test_refuses_root_and_production_paths(backup, destination):
    r = restore(backup, destination)
    assert r.returncode != 0
    assert 'protected production path' in r.stderr or 'already exists' in r.stderr, r.stderr


def test_refuses_existing_destination_and_the_backup_root(backup, tmp_path):
    existing = tmp_path / 'exists'
    existing.mkdir()
    assert restore(backup, existing).returncode != 0
    assert restore(backup, backup[0] / 'inside').returncode != 0
