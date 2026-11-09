"""Fitness downgrade must preserve post-MRK-42 School facts on SQLite and scratch PostgreSQL."""
import os
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import models
from database import Base

FITNESS_TABLES = {
    'fitness_exercises', 'fitness_workouts', 'fitness_workout_sets',
    'fitness_rehab_exercises', 'fitness_rehab_sessions', 'fitness_rehab_entries',
}


@pytest.mark.parametrize('dialect', ['sqlite', 'postgresql'])
def test_fitness_roundtrip_preserves_school_facts(dialect, tmp_path, monkeypatch):
    # Existing migration tests reload Alembic during collection; resolve its API at test time.
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.script import ScriptDirectory
    if dialect == 'postgresql':
        url = os.environ.get('TEST_POSTGRES_URL')
        if not url:
            pytest.skip('TEST_POSTGRES_URL not set; disposable PostgreSQL only')
        parsed = make_url(url)
        assert parsed.get_backend_name() == 'postgresql' and 'test' in (parsed.database or '')
    else:
        url = 'sqlite+pysqlite:///' + str(tmp_path / 'fitness-migration.db')
    monkeypatch.setenv('DATABASE_URL', url)
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / 'alembic.ini'))
    cfg.set_main_option('script_location', str(backend / 'alembic'))
    cfg.set_main_option('version_locations', str(backend / 'alembic/versions'))
    scripts = ScriptDirectory.from_config(cfg)
    # MRK-96: no hardcoded head – exactly one head, and Fitness is on its linear history
    heads = scripts.get_heads()
    assert len(heads) == 1, heads
    head = heads[0]
    assert '0022_fitness' in {rev.revision for rev in scripts.walk_revisions('base', head)}
    assert scripts.get_revision('0022_fitness').down_revision == '0021_study_materials'
    assert scripts.get_revision('0021_study_materials').down_revision == '0020_calendar_source_presence'

    # Stop before Fitness; seed meaningful mapping, extracted text and source absence facts.
    command.upgrade(cfg, '0021_study_materials')
    engine = create_engine(url)
    try:
        assert {'study_courses', 'study_materials'} <= set(inspect(engine).get_table_names())
        with Session(engine) as db:
            # subjects jen se sloupci, které existují v 0021 (MRK-86 přidal další) – ne přes ORM model
            subjects = Base.metadata.tables['subjects']
            subject_id = db.execute(subjects.insert().values(name='Synthetic preservation subject', active=True)
                                    .returning(subjects.c.id)).scalar_one()
            course = models.StudyCourse(source='moodle', external_id='mrk33-preservation',
                                       name='Synthetic preservation course', subject_id=subject_id)
            db.add(course)
            db.flush()
            db.add(models.StudyMaterial(course_id=course.id, external_id='7:/synthetic.txt',
                module_external_id='7', title='Synthetic historical material', file_name='synthetic.txt',
                material_type='txt', download_status='stored', stored_name='a' * 64 + '.txt',
                checksum='a' * 64, stored_size=19, extraction_status='ok',
                extracted_text='Synthetic preserved text', source_missing_at=datetime(2026, 1, 2),
                source_modified_at=datetime(2026, 1, 1)))
            db.commit()

        def snapshot():
            def columns(name):
                table = Base.metadata.tables[name]
                if name == 'subjects':  # sloupce z doby 0021 (pozdější migrace přidávají nullable sloupce)
                    return [table.c[c] for c in ('id', 'name', 'code', 'semester', 'credits', 'active')]
                return list(table.c)
            with engine.connect() as connection:
                return {name: connection.execute(select(*columns(name))
                        .order_by(Base.metadata.tables[name].c.id)).all()
                        for name in ('subjects', 'study_courses', 'study_materials')}

        before = snapshot()
        command.upgrade(cfg, '0022_fitness')
        assert FITNESS_TABLES <= set(inspect(engine).get_table_names())
        assert snapshot() == before
        command.downgrade(cfg, '-1')
        tables = set(inspect(engine).get_table_names())
        assert not FITNESS_TABLES & tables
        assert {'study_courses', 'study_materials'} <= tables
        assert snapshot() == before
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == '0021_study_materials'
        command.upgrade(cfg, 'head')
        assert FITNESS_TABLES <= set(inspect(engine).get_table_names())
        assert snapshot() == before
        with engine.connect() as connection:
            ctx = MigrationContext.configure(connection)
            assert ctx.get_current_revision() == head
            assert compare_metadata(ctx, Base.metadata) == []
    finally:
        engine.dispose()
