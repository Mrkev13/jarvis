"""MRK-101: the Ubuntu production Compose files and Dockerfiles stay safe and match what the deploy relies on.

`docker compose config` itself runs in CI (ci.yml); these checks pin the parts the deploy (MRK-108), the backup
timer and docs/ubuntu-deployment.md rely on, and that no secret or public port ever lands in the repository.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def compose(name):
    return yaml.safe_load((ROOT / name / 'compose.yaml').read_text(encoding='utf-8'))


BACKEND_FILE = compose('backend')
BACKEND = BACKEND_FILE['services']['backend']
MIGRATE = BACKEND_FILE['services']['migrate']
FRONTEND = compose('frontend')['services']['frontend']
POSTGRES = compose('postgres')['services']['postgres']
TEXT = ''.join((ROOT / n / 'compose.yaml').read_text() for n in ('backend', 'frontend', 'postgres'))


def test_names_and_images_the_deploy_and_backup_rely_on():
    assert (BACKEND['image'], BACKEND['container_name']) == ('standa-hub-backend:local', 'standa-hub-backend')
    assert (FRONTEND['image'], FRONTEND['container_name']) == ('standa-hub-frontend:local', 'standa-hub-frontend')
    assert POSTGRES['container_name'] == 'standa-postgres'
    assert MIGRATE['image'] == BACKEND['image'] and MIGRATE['command'] == ['alembic', 'upgrade', 'head']
    assert BACKEND['depends_on'] == {'migrate': {'condition': 'service_completed_successfully'}}, 'migrate before start'


def test_restart_policy_and_health_checks():
    for service in (BACKEND, FRONTEND, POSTGRES):
        assert service['restart'] == 'unless-stopped'
        assert service['healthcheck']['retries'] >= 3
    assert MIGRATE['restart'] == 'no'
    assert 'http://127.0.0.1:8000/health' in ' '.join(BACKEND['healthcheck']['test'])
    assert 'http://127.0.0.1:3000/login' in ' '.join(FRONTEND['healthcheck']['test'])


def test_ports_only_on_localhost():
    """Remote access goes through Tailscale Serve only."""
    for service in (BACKEND, FRONTEND, POSTGRES):
        assert service['ports'] and all(p.startswith('127.0.0.1:') for p in service['ports']), service['ports']
    assert 'ports' not in MIGRATE


def test_running_commit_reaches_health():
    assert BACKEND['environment'] == {'APP_COMMIT': '${APP_COMMIT:-}'}


def test_no_secret_in_the_repository():
    for service in (BACKEND, MIGRATE):
        assert service['env_file'] == [{'path': '.env.production', 'format': 'raw'}]
    assert POSTGRES['environment']['POSTGRES_PASSWORD'] == '${POSTGRES_PASSWORD}'
    assert FRONTEND['environment']['NEXT_PUBLIC_API_URL'].startswith('${NEXT_PUBLIC_API_URL')
    assert not re.search(r'ts\.net|postgres(ql)?(\+\w+)?://|TOKEN=|_KEY=', TEXT, re.I)
    for name in ('backend', 'frontend'):
        ignore = (ROOT / name / '.dockerignore').read_text().split()
        assert '.env' in ignore and '.env.*' in ignore, f'{name}: env files never go into an image'
    ignored = (ROOT / '.gitignore').read_text()
    assert '/postgres/.env' in ignored


def test_data_and_database_wiring():
    assert BACKEND['volumes'] == ['/srv/standa-hub-data/media:/data/media', '/srv/standa-hub-data/backups:/data/backups']
    assert BACKEND_FILE['networks']['postgres_net'] == {'external': True, 'name': 'postgres_default'}
    assert POSTGRES['volumes'] == ['postgres_data:/var/lib/postgresql']


def test_dockerfiles():
    assert 'postgresql-client-18' in (ROOT / 'backend' / 'Dockerfile').read_text(), 'pg_dump for backup_service'
    frontend = (ROOT / 'frontend' / 'Dockerfile').read_text()
    assert 'ARG NEXT_PUBLIC_API_URL' in frontend and 'test -n "$NEXT_PUBLIC_API_URL"' in frontend
    assert frontend.index('test -n') < frontend.index('npm run build'), 'fail before building without an API origin'
