"""MRK-101: the Ubuntu production Compose files and Dockerfiles stay safe and match what the server runs.

`docker compose config` itself runs in CI (ci.yml); these checks pin the parts the deploy (MRK-108) and the
operations docs rely on, and that no secret or public port ever lands in the repository.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = yaml.safe_load((ROOT / 'backend' / 'compose.yaml').read_text(encoding='utf-8'))['services']['backend']
FRONTEND = yaml.safe_load((ROOT / 'frontend' / 'compose.yaml').read_text(encoding='utf-8'))['services']['frontend']
COMPOSE_TEXT = (ROOT / 'backend' / 'compose.yaml').read_text() + (ROOT / 'frontend' / 'compose.yaml').read_text()


def test_names_and_images_the_deploy_and_backup_rely_on():
    assert (BACKEND['image'], BACKEND['container_name']) == ('standa-hub-backend:local', 'standa-hub-backend')
    assert (FRONTEND['image'], FRONTEND['container_name']) == ('standa-hub-frontend:local', 'standa-hub-frontend')
    assert BACKEND['build']['context'] == '.' and FRONTEND['build']['context'] == '.'
    assert FRONTEND['build']['args']['NEXT_PUBLIC_API_URL'] == '${NEXT_PUBLIC_API_URL:-}'


def test_restart_policy_and_health_checks():
    for service in (BACKEND, FRONTEND):
        assert service['restart'] == 'unless-stopped'
        assert service['healthcheck']['test'][0] == 'CMD' and service['healthcheck']['retries'] >= 3
    assert 'http://127.0.0.1:8000/health' in BACKEND['healthcheck']['test']
    assert 'http://127.0.0.1:3000/login' in ' '.join(FRONTEND['healthcheck']['test'])


def test_ports_only_on_localhost():
    """Public access goes through Tailscale Serve only (docs/operations.md)."""
    for service in (BACKEND, FRONTEND):
        assert service['ports'] and all(p.startswith('127.0.0.1:') for p in service['ports']), service['ports']


def test_no_secret_in_the_repository():
    assert BACKEND['env_file'] == [{'path': '.env.production', 'format': 'raw'}]
    assert set(BACKEND['environment']) == {'APP_COMMIT'} and BACKEND['environment']['APP_COMMIT'] == '${APP_COMMIT:-}'
    assert set(FRONTEND['environment']) == {'NEXT_PUBLIC_API_URL', 'NODE_ENV'}
    assert FRONTEND['environment']['NEXT_PUBLIC_API_URL'] == '${NEXT_PUBLIC_API_URL:-}', 'no real host name in git'
    assert not re.search(r'ts\.net|postgres(ql)?://|PASSWORD=|_KEY=|TOKEN=', COMPOSE_TEXT, re.I)
    for name in ('backend', 'frontend'):
        ignore = (ROOT / name / '.dockerignore').read_text().split()
        assert '.env' in ignore and '.env.*' in ignore, f'{name}: env files never go into an image'


def test_data_and_database_wiring():
    assert BACKEND['volumes'] == ['/srv/standa-hub-data/media:/data/media', '/srv/standa-hub-data/backups:/data/backups']
    networks = yaml.safe_load((ROOT / 'backend' / 'compose.yaml').read_text())['networks']
    assert networks['postgres_net'] == {'external': True, 'name': 'postgres_default'}


def test_dockerfiles():
    backend = (ROOT / 'backend' / 'Dockerfile').read_text()
    assert 'postgresql-client-18' in backend, 'pg_dump for backup_service'
    assert backend.startswith('# MRK-101') and 'FROM python:3.12-slim' in backend
    frontend = (ROOT / 'frontend' / 'Dockerfile').read_text()
    assert 'ARG NEXT_PUBLIC_API_URL' in frontend and 'test -n "$NEXT_PUBLIC_API_URL"' in frontend
    assert frontend.index('test -n') < frontend.index('npm run build'), 'fail before building without an API origin'
