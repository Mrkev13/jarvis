"""MRK-101 review: the emptiness query of deploy/scripts/restore-postgres-test.sh counts EVERY user object
of the restore target, not only public base tables. Real PostgreSQL only: TEST_POSTGRES_URL (CI job "PostgreSQL
migration round-trip"); each case uses its own throwaway database whose name contains "test"."""
import os
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / 'deploy' / 'scripts' / 'restore-postgres-test.sh').read_text()
SQL = SCRIPT.split("<<'EMPTY_SQL'\n", 1)[1].split('\nEMPTY_SQL\n', 1)[0]  # exactly the text the script runs
URL = os.environ.get('TEST_POSTGRES_URL', '')


def test_restore_script_uses_the_full_emptiness_check():
    assert 'pg_class' in SQL and 'pg_proc' in SQL and 'pg_extension' in SQL
    assert "table_schema='public' AND table_type='BASE TABLE'" not in SCRIPT


@pytest.fixture
def scratch():
    if not URL:
        pytest.skip('TEST_POSTGRES_URL not set; disposable PostgreSQL only')
    sqlalchemy = pytest.importorskip('sqlalchemy')
    admin = sqlalchemy.create_engine(URL, isolation_level='AUTOCOMMIT')
    name = f'restore_empty_test_{uuid.uuid4().hex[:10]}'
    with admin.connect() as c:
        c.exec_driver_sql(f'CREATE DATABASE {name}')
    engine = sqlalchemy.create_engine(admin.url.set(database=name), isolation_level='AUTOCOMMIT')
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS {name}')
        admin.dispose()


def count(engine):
    import sqlalchemy
    with engine.connect() as c:
        return c.execute(sqlalchemy.text(SQL)).scalar_one()  # text(): the LIKE patterns contain %


def test_fresh_database_is_empty(scratch):
    assert count(scratch) == 0


@pytest.mark.parametrize('ddl', [
    'CREATE TABLE public.t (id int)',
    'CREATE SCHEMA other; CREATE TABLE other.t (id int)',
    'CREATE SCHEMA other',
    'CREATE VIEW public.v AS SELECT 1 AS x',
    'CREATE SEQUENCE public.s',
    'CREATE MATERIALIZED VIEW public.mv AS SELECT 1 AS x',
    'CREATE FUNCTION public.f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$',
    "CREATE TYPE public.mood AS ENUM ('ok')",
    'CREATE DOMAIN public.pos AS int CHECK (VALUE > 0)',
    'CREATE TYPE public.pair AS (a int, b int)',
], ids=['public table', 'table in other schema', 'empty other schema', 'view', 'sequence', 'materialized view',
        'function', 'enum', 'domain', 'composite type'])
def test_any_user_object_makes_the_target_non_empty(scratch, ddl):
    with scratch.connect() as c:
        for statement in ddl.split('; '):
            c.exec_driver_sql(statement)
    assert count(scratch) > 0
