"""Synthetic Fitness history, API and framework regressions; no real DB or network calls."""
import json
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import models
from database import Base

DAY = date(2026, 10, 9)


@pytest.fixture
def db():
    engine=create_engine('sqlite+pysqlite:///:memory:',poolclass=StaticPool,connect_args={'check_same_thread':False})
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def definition(db, kind='strength'):
    from modules.fitness import service, schemas
    return service.create_exercise(db, schemas.ExerciseCreate(name='Synthetic squat',type=kind))


def workout(db, exercise, **kwargs):
    from modules.fitness import service, schemas
    return service.create_workout(db, schemas.WorkoutCreate(performed_on=DAY,
        sets=[dict(exercise_id=exercise.id,order_index=1,reps=5,weight_kg=40),
              dict(exercise_id=exercise.id,order_index=0,reps=8,weight_kg=30)], **kwargs), today=DAY)


def test_workout_transaction_order_snapshot_archive_restore(db):
    from modules.fitness import service,schemas
    e=definition(db)
    w=workout(db,e)
    db.commit()
    assert [s.order_index for s in service.get_workout(db,w.id).sets]==[0,1]
    service.update_exercise(db,e.id,schemas.ExercisePatch(active=False,name='Renamed definition'))
    db.commit()
    payload=service.workout_dict(service.get_workout(db,w.id))
    assert payload['sets'][0]['exercise_name']=='Synthetic squat'
    assert len(payload['sets'])==2
    with pytest.raises(service.FitnessError):
        workout(db,e)
    db.rollback()
    service.update_exercise(db,e.id,schemas.ExercisePatch(active=True))
    db.commit()
    assert e.active
    assert db.query(models.WorkoutSession).count()==1


def test_invalid_reference_all_or_nothing_and_event_rollback(db):
    from modules.fitness import service,schemas
    e=definition(db);db.commit()
    before=db.query(models.DomainEvent).count()
    body=schemas.WorkoutCreate(performed_on=DAY,sets=[dict(exercise_id=e.id,order_index=0,reps=5),dict(exercise_id=999,order_index=1,reps=5)])
    with pytest.raises(service.FitnessError):
        service.create_workout(db,body,today=DAY)
    db.rollback()
    assert db.query(models.WorkoutSession).count()==0
    assert db.query(models.DomainEvent).count()==before
    with patch('modules.fitness.service.append_domain_event',side_effect=RuntimeError('intentional')):
        with pytest.raises(RuntimeError):
            workout(db,e)
    db.rollback()
    assert db.query(models.WorkoutSet).count()==0


@pytest.mark.parametrize('kind,measure,valid',[
    ('strength',{'reps':0,'weight_kg':0},True),('bodyweight',{'reps':8},True),
    ('duration',{'duration_seconds':60},True),('distance',{'distance_m':500,'duration_seconds':120},True),
    ('strength',{'duration_seconds':10},False),('bodyweight',{'reps':5,'weight_kg':10},False),
    ('duration',{'reps':1,'duration_seconds':10},False),('distance',{'reps':1,'distance_m':10},False),
])
def test_exercise_types(db,kind,measure,valid):
    from modules.fitness import service,schemas
    e=definition(db,kind);db.commit()
    body=schemas.WorkoutCreate(performed_on=DAY,sets=[dict(exercise_id=e.id,order_index=0,**measure)])
    if valid:
        assert service.create_workout(db,body,today=DAY).id
    else:
        with pytest.raises(service.FitnessError):
            service.create_workout(db,body,today=DAY)
        db.rollback()
        assert db.query(models.WorkoutSession).count()==0


@pytest.mark.parametrize('fields', [{'reps':-1},{'weight_kg':-1},{'rir':11},{'duration_seconds':0},
                                    {'distance_m':0},{'reps':1.5},{'weight_kg':float('nan')},{'order_index':-1}])
def test_numeric_bounds(fields):
    from modules.fitness.schemas import WorkoutSetWrite
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        WorkoutSetWrite(**{'exercise_id':1,'order_index':0,'reps':5,**fields})


def test_duplicate_order_future_date_and_immutable_entries(db):
    from modules.fitness import service,schemas
    e=definition(db)
    body=schemas.WorkoutCreate(performed_on=DAY,sets=[dict(exercise_id=e.id,order_index=0,reps=5)]*2)
    with pytest.raises(service.FitnessError):
        service.create_workout(db,body,today=DAY)
    body=schemas.WorkoutCreate(performed_on=date(2026,10,10),sets=[dict(exercise_id=e.id,order_index=0,reps=5)])
    with pytest.raises(service.FitnessError):
        service.create_workout(db,body,today=DAY)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        schemas.WorkoutPatch(sets=[])


def test_metadata_correction_preserved_no_op_quiet_and_type_locked(db):
    from modules.fitness import service,schemas
    e=definition(db);w=workout(db,e,notes='original notes');db.commit()
    count=db.query(models.DomainEvent).count()
    service.update_workout(db,w.id,schemas.WorkoutPatch(notes='corrected notes'),today=DAY);db.commit()
    audit=db.query(models.ActivityLog).order_by(models.ActivityLog.id.desc()).first()
    assert 'original notes' in audit.delta_json and 'corrected notes' in audit.delta_json
    assert db.query(models.DomainEvent).count()==count+1
    service.update_workout(db,w.id,schemas.WorkoutPatch(notes='corrected notes'),today=DAY);db.commit()
    assert db.query(models.DomainEvent).count()==count+1
    with pytest.raises(service.FitnessError):
        service.update_exercise(db,e.id,schemas.ExercisePatch(type='duration'))
    assert [s.reps for s in w.sets]==[8,5]
    assert all('notes' not in event.payload for event in db.query(models.DomainEvent).all())


def test_rehab_multi_entry_archive_pain_and_history(db):
    from modules.fitness import service,schemas
    e=service.create_rehab_exercise(db,schemas.RehabExerciseCreate(name='Synthetic balance',type='duration',body_area='knee'))
    r=service.create_rehab_session(db,schemas.RehabSessionCreate(performed_on=DAY,entries=[
        dict(rehab_exercise_id=e.id,order_index=0,duration_seconds=30,sets=2,pain_before=2,pain_after=1),
        dict(rehab_exercise_id=e.id,order_index=1,duration_seconds=45,sets=1)]),today=DAY)
    db.commit()
    service.update_rehab_exercise(db,e.id,schemas.RehabExercisePatch(active=False));db.commit()
    assert len(service.get_rehab_session(db,r.id).entries)==2
    with pytest.raises(service.FitnessError):
        service.create_rehab_session(db,schemas.RehabSessionCreate(performed_on=DAY,entries=[dict(rehab_exercise_id=e.id,order_index=0,duration_seconds=30)]),today=DAY)
    db.rollback()
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        schemas.RehabEntryWrite(rehab_exercise_id=e.id,order_index=0,duration_seconds=30,pain_after=11)


def test_definition_hard_delete_restricted(db):
    from sqlalchemy.exc import IntegrityError
    e=definition(db);workout(db,e);db.commit()
    with pytest.raises(IntegrityError):
        db.execute(text('DELETE FROM fitness_exercises WHERE id=:id'),{'id':e.id})
        db.commit()
    db.rollback()
    assert db.query(models.WorkoutSet).count()==2


def test_progress_providers_dedupe_disable_no_timeline(db):
    from modules.fitness import service,integrations
    from module_registry import ModuleAccess
    from module_contracts import ContextRequest
    from today_types import TodayContext
    from change_feed import build
    e=definition(db);w=workout(db,e);db.commit()
    data=service.progress(db,today=DAY)
    assert data['week_workouts']==1 and data['week_rehab_sessions']==0
    assert service.exercise_progress(db,e.id)['last_performed_on']==DAY.isoformat()
    access=ModuleAccess({})
    result=build(db,access,since=datetime(2020,1,1,tzinfo=timezone.utc),modules=None,limit=100)
    assert len([i for i in result['items'] if i['module_id']=='fitness'])==2
    assert db.query(models.DomainEvent).count()==2  # definition + session; no per-set spam
    assert any(c[1]==w.id for c in integrations.search_fitness(db,'Synthetic'))
    context=ContextRequest(db,DAY,datetime(2026,10,9))
    assert '1' in ' '.join(integrations.context_fitness(context))
    today=integrations.today_fitness(TodayContext(db,datetime(2026,10,9),DAY,datetime(2026,10,9)))
    assert today[0].status=='done' and today[0].time is None
    off=ModuleAccess({'fitness':False})
    for key in ('search','today','context','changes'):
        assert not any(owner=='fitness' for owner,_ in off.contributions(key))
    assert not integrations.INTEGRATIONS.timeline
    assert len(json.loads(db.query(models.ActivityLog).first().delta_json))>0


def test_rehab_invalid_batch_and_metadata_history(db):
    from modules.fitness import service,schemas
    e=service.create_rehab_exercise(db,schemas.RehabExerciseCreate(name='Synthetic rehab',type='bodyweight'))
    db.commit()
    body=schemas.RehabSessionCreate(performed_on=DAY,entries=[dict(rehab_exercise_id=e.id,order_index=0,reps=5),dict(rehab_exercise_id=999,order_index=1,reps=5)])
    with pytest.raises(service.FitnessError):
        service.create_rehab_session(db,body,today=DAY)
    db.rollback()
    assert db.query(models.RehabSession).count()==0
    body=schemas.RehabSessionCreate(performed_on=DAY,notes='before',entries=[dict(rehab_exercise_id=e.id,order_index=0,reps=5)])
    row=service.create_rehab_session(db,body,today=DAY);db.commit()
    service.update_rehab_session(db,row.id,schemas.RehabSessionPatch(notes='after'),today=DAY);db.commit()
    assert 'before' in db.query(models.ActivityLog).order_by(models.ActivityLog.id.desc()).first().delta_json
    with pytest.raises(service.FitnessError):
        service.update_rehab_exercise(db,e.id,schemas.RehabExercisePatch(type='duration'))
    db.rollback()
    service.update_rehab_exercise(db,e.id,schemas.RehabExercisePatch(active=False));db.commit()
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db.execute(text('DELETE FROM fitness_rehab_exercises WHERE id=:id'),{'id':e.id})
        db.commit()
    db.rollback()
    assert db.query(models.RehabEntry).count()==1


def test_api_auth_module_gate_and_atomic_invalid_set(db,monkeypatch):
    import database,main
    from modules.fitness import service
    monkeypatch.setattr(service,'today_local',lambda:DAY)
    from module_registry import ModuleAccess
    from fastapi.testclient import TestClient
    monkeypatch.setattr(database,'SessionLocal',lambda:Session(db.bind))
    monkeypatch.setattr(main,'auth_enabled',lambda:True)
    monkeypatch.setattr(main,'validate_session_token',lambda token:None)
    monkeypatch.setattr(main,'current_access',lambda:ModuleAccess({'fitness':True}))
    client=TestClient(main.app)
    assert client.get('/fitness/workouts').status_code==401
    monkeypatch.setattr(main,'auth_enabled',lambda:False)
    monkeypatch.setattr(main,'current_access',lambda:ModuleAccess({'fitness':False}))
    assert client.get('/fitness/workouts').status_code==404
    monkeypatch.setattr(main,'current_access',lambda:ModuleAccess({'fitness':True}))
    e=client.post('/fitness/exercises',json={'name':'API synthetic','type':'strength'}).json()
    bad=client.post('/fitness/workouts',json={'performed_on':DAY.isoformat(),'sets':[
        {'exercise_id':e['id'],'order_index':0,'reps':5},{'exercise_id':999,'order_index':1,'reps':5}]})
    assert bad.status_code==422
    assert client.get('/fitness/workouts').json()=={'workouts':[]}
    saved=client.post('/fitness/workouts',json={'performed_on':DAY.isoformat(),'sets':[{'exercise_id':e['id'],'order_index':0,'reps':5}]})
    assert saved.status_code==200
    assert client.get(f"/fitness/workouts/{saved.json()['id']}").json()['sets'][0]['reps']==5
    assert client.delete(f"/fitness/exercises/{e['id']}").status_code==405


def test_actual_search_today_context_and_bounded_loading(db):
    from modules.fitness import service,schemas
    from module_registry import ModuleAccess
    from search_service import search
    from today_service import build_today
    from context_service import build_current_context
    e=definition(db);db.commit()
    queries=[]
    def count_queries(conn,cursor,statement,parameters,context,executemany):
        queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',count_queries)
    try:
        body=schemas.WorkoutCreate(performed_on=DAY,title='Synthetic session',sets=[dict(exercise_id=e.id,order_index=i,reps=5) for i in range(50)])
        service.create_workout(db,body,today=DAY);db.commit()
        assert len([q for q in queries if q.startswith('SELECT') and 'FROM fitness_exercises' in q])<=2
        queries.clear();db.expunge_all()
        assert len(service.list_workouts(db)['workouts'][0]['sets'])==50
        assert len(queries)==2  # parents + one selectin batch; no per-set definition loading
    finally:
        event.remove(db.bind,'before_cursor_execute',count_queries)
    on,off=ModuleAccess({}),ModuleAccess({'fitness':False})
    assert any(r['type']=='fitness_workout' for r in search(db,'Synthetic',access=on)['results'])
    assert not any(r['area']=='fitness' for r in search(db,'Synthetic',access=off)['results'])
    now=datetime(2026,10,9,12)
    assert 'Synthetic session' in str(build_today(db,now_utc=now,access=on))
    assert 'Synthetic session' not in str(build_today(db,now_utc=now,access=off))
    assert 'Synthetic session' in str(build_current_context(db,'fitness trénink',now_utc=now,access=on))
    assert 'Synthetic session' not in str(build_current_context(db,'fitness trénink',now_utc=now,access=off))
