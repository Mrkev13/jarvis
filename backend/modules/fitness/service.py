"""Caller-owned transactions; immutable measurements, audited metadata corrections."""
from datetime import date, timezone

from sqlalchemy import func
from sqlalchemy.orm import selectinload

from domain_events import ActivityProjection, append_domain_event
from modules.fitness.models import Exercise, WorkoutSession, WorkoutSet, RehabExercise, RehabSession, RehabEntry
from time_utils import local_week_bounds_utc, today_local, utc_now


class FitnessError(ValueError):
    def __init__(self,status,message):
        self.status,self.message=status,message
        super().__init__(message)


def _iso(value):
    if hasattr(value,'hour'):
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.isoformat() if isinstance(value,date) else value


def _columns(row):
    return {c.name:_iso(getattr(row,c.name)) for c in row.__table__.columns}


def exercise_dict(row):
    return _columns(row)


def rehab_exercise_dict(row):
    return _columns(row)


def workout_dict(row):
    return {**_columns(row),'sets':[_columns(s) for s in row.sets]}


def rehab_session_dict(row):
    return {**_columns(row),'entries':[_columns(e) for e in row.entries]}


def _fact(db,kind,action,row,summary,before,after):
    delta={key:{'old':before.get(key),'new':value} for key,value in after.items() if before.get(key)!=value}
    if not delta:
        return
    payload={'id':row.id}
    if hasattr(row,'performed_on'):
        payload.update(date=row.performed_on.isoformat(),count=len(row.sets if kind=='workout' else row.entries))
    else:
        payload['active']=row.active
    append_domain_event(db,event_type=f'fitness.{kind}.{action}',aggregate_type=f'fitness_{kind}',aggregate_id=row.id,
                        payload=payload,activity=ActivityProjection('fitness',action,summary,f'fitness_{kind}',row.id,delta,'manual'))


def list_exercises(db):
    return {'exercises':[exercise_dict(e) for e in db.query(Exercise).order_by(Exercise.name,Exercise.id).limit(500).all()]}


def list_rehab_exercises(db):
    return {'exercises':[rehab_exercise_dict(e) for e in db.query(RehabExercise).order_by(RehabExercise.name,RehabExercise.id).limit(500).all()]}


def create_exercise(db,body):
    row=Exercise(**body.model_dump())
    db.add(row);db.flush()
    _fact(db,'exercise','created',row,f'Nový cvik: {row.name}',{},exercise_dict(row))
    return row


def create_rehab_exercise(db,body):
    row=RehabExercise(**body.model_dump())
    db.add(row);db.flush()
    _fact(db,'rehab_exercise','created',row,f'Nový rehab cvik: {row.name}',{},rehab_exercise_dict(row))
    return row


def _get_definition(db,model,identity):
    row=db.query(model).filter(model.id==identity).populate_existing().with_for_update().one_or_none()
    if row is None:
        raise FitnessError(404,'Cvik neexistuje.')
    return row


def _update_definition(db,row,body,kind,child,child_fk):
    values=body.model_dump(exclude_unset=True)
    for key in ('name','type','category','active'):
        if key in values and values[key] is None:
            raise FitnessError(422,'Povinné pole nesmí být prázdné.')
    if values.get('type',row.type)!=row.type and db.query(child.id).filter(child_fk==row.id).first():
        raise FitnessError(409,'Typ cviku s historií nelze změnit. Založ nový cvik.')
    before=_columns(row)
    for key,value in values.items():
        setattr(row,key,value)
    if 'active' in values and before['active']!=row.active:
        row.archived_at=None if row.active else utc_now()
    after=_columns(row)
    if before==after:
        return row
    action=('restored' if row.active else 'archived') if before['active']!=row.active else 'updated'
    label={'restored':'Obnoven','archived':'Archivován','updated':'Upraven'}[action]
    db.flush()
    _fact(db,kind,action,row,f'{label} cvik: {row.name}',before,after)
    return row


def update_exercise(db,identity,body):
    row=_get_definition(db,Exercise,identity)
    return _update_definition(db,row,body,'exercise',WorkoutSet,WorkoutSet.exercise_id)


def update_rehab_exercise(db,identity,body):
    row=_get_definition(db,RehabExercise,identity)
    return _update_definition(db,row,body,'rehab_exercise',RehabEntry,RehabEntry.rehab_exercise_id)


def _day(day,today):
    if day is None or day>(today or today_local()):
        raise FitnessError(422,'Záznam musí mít datum dnes nebo v minulosti.')


def _measurements(kind,row):
    fields=('reps','weight_kg','duration_seconds','distance_m','rir')
    required={'strength':'reps','bodyweight':'reps','duration':'duration_seconds','distance':'distance_m'}[kind]
    allowed={'strength':{'reps','weight_kg','rir'},'bodyweight':{'reps','rir'},
             'duration':{'duration_seconds'},'distance':{'distance_m','duration_seconds'}}[kind]
    if getattr(row,required,None) is None or any(getattr(row,key,None) is not None for key in fields if key not in allowed):
        raise FitnessError(422,'Hodnoty neodpovídají typu cviku.')


def _definitions(db,model,entries,key):
    ids={getattr(e,key) for e in entries}
    rows=db.query(model).filter(model.id.in_(ids)).order_by(model.id).populate_existing().with_for_update().all()
    definitions={e.id:e for e in rows}
    if ids!=definitions.keys():
        raise FitnessError(422,'Některý cvik neexistuje.')
    if any(not e.active for e in rows):
        raise FitnessError(409,'Archivovaný cvik nelze použít v novém záznamu.')
    order=[entry.order_index for entry in entries]
    if len(set(order))!=len(order):
        raise FitnessError(422,'Pořadí položek nesmí být duplicitní.')
    for entry in entries:
        _measurements(definitions[getattr(entry,key)].type,entry)
    return definitions


def create_workout(db,body,*,today=None):
    _day(body.performed_on,today)
    definitions=_definitions(db,Exercise,body.sets,'exercise_id')
    row=WorkoutSession(**body.model_dump(exclude={'sets'}),source='manual')
    row.sets=[WorkoutSet(**entry.model_dump(),exercise_name=definitions[entry.exercise_id].name,
                        exercise_type=definitions[entry.exercise_id].type) for entry in sorted(body.sets,key=lambda s:s.order_index)]
    db.add(row);db.flush()
    _fact(db,'workout','created',row,f'Zapsán trénink: {row.title or row.performed_on.isoformat()}',{},workout_dict(row))
    return row


def create_rehab_session(db,body,*,today=None):
    _day(body.performed_on,today)
    definitions=_definitions(db,RehabExercise,body.entries,'rehab_exercise_id')
    row=RehabSession(**body.model_dump(exclude={'entries'}))
    row.entries=[RehabEntry(**entry.model_dump(),exercise_name=definitions[entry.rehab_exercise_id].name,
                           exercise_type=definitions[entry.rehab_exercise_id].type) for entry in sorted(body.entries,key=lambda e:e.order_index)]
    db.add(row);db.flush()
    _fact(db,'rehab_session','created',row,f'Zapsána rehabilitace: {row.performed_on.isoformat()}',{},rehab_session_dict(row))
    return row


def workouts_query(db):
    return db.query(WorkoutSession).options(selectinload(WorkoutSession.sets))


def rehab_query(db):
    return db.query(RehabSession).options(selectinload(RehabSession.entries))


def get_workout(db,identity):
    row=workouts_query(db).filter(WorkoutSession.id==identity).populate_existing().one_or_none()
    if row is None:
        raise FitnessError(404,'Trénink neexistuje.')
    return row


def get_rehab_session(db,identity):
    row=rehab_query(db).filter(RehabSession.id==identity).populate_existing().one_or_none()
    if row is None:
        raise FitnessError(404,'Rehabilitace neexistuje.')
    return row


def list_workouts(db,limit=50):
    return {'workouts':[workout_dict(row) for row in workouts_query(db).order_by(WorkoutSession.performed_on.desc(),WorkoutSession.id.desc()).limit(limit).all()]}


def list_rehab_sessions(db,limit=50):
    return {'sessions':[rehab_session_dict(row) for row in rehab_query(db).order_by(RehabSession.performed_on.desc(),RehabSession.id.desc()).limit(limit).all()]}


def _update_session(db,row,body,kind,serialize,today):
    values=body.model_dump(exclude_unset=True)
    if 'performed_on' in values:
        _day(values['performed_on'],today)
    before=serialize(row)
    for key,value in values.items():
        setattr(row,key,value)
    after=serialize(row)
    if before!=after:
        row.updated_at=utc_now()
        db.flush()
        _fact(db,kind,'updated',row,'Upraven trénink' if kind=='workout' else 'Upravena rehabilitace',before,serialize(row))
    return row


def update_workout(db,identity,body,*,today=None):
    db.query(WorkoutSession.id).filter(WorkoutSession.id==identity).with_for_update().first()
    return _update_session(db,get_workout(db,identity),body,'workout',workout_dict,today)


def update_rehab_session(db,identity,body,*,today=None):
    db.query(RehabSession.id).filter(RehabSession.id==identity).with_for_update().first()
    return _update_session(db,get_rehab_session(db,identity),body,'rehab_session',rehab_session_dict,today)


def progress(db,*,today=None):
    today=today or today_local()
    monday=local_week_bounds_utc(today)[0]
    from time_utils import to_local
    start=to_local(monday).date()
    return {'week_start':start.isoformat(),
            'week_workouts':db.query(func.count(WorkoutSession.id)).filter(WorkoutSession.performed_on>=start,WorkoutSession.performed_on<=today).scalar(),
            'week_rehab_sessions':db.query(func.count(RehabSession.id)).filter(RehabSession.performed_on>=start,RehabSession.performed_on<=today).scalar(),
            'recent_workouts':list_workouts(db,5)['workouts'],'recent_rehab_sessions':list_rehab_sessions(db,5)['sessions']}


def exercise_progress(db,identity):
    if db.get(Exercise,identity) is None:
        raise FitnessError(404,'Cvik neexistuje.')
    rows=(db.query(WorkoutSet,WorkoutSession.performed_on).join(WorkoutSession)
          .filter(WorkoutSet.exercise_id==identity,WorkoutSet.completed.is_(True))
          .order_by(WorkoutSession.performed_on.desc(),WorkoutSession.id.desc(),WorkoutSet.order_index).limit(200).all())
    last_session=rows[0][0].workout_session_id if rows else None
    return {'exercise_id':identity,'last_performed_on':rows[0][1].isoformat() if rows else None,
            'last_sets':[_columns(s) for s,_day in rows if s.workout_session_id==last_session],
            'recent_sessions':list(dict.fromkeys(s.workout_session_id for s,_day in rows))[:20]}
