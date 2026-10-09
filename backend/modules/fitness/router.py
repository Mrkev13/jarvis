"""Explicit authenticated routes; global module gate applies through the registry."""
from fastapi import APIRouter, HTTPException
import database
from modules.fitness import schemas,service

router=APIRouter(prefix='/fitness',tags=['fitness'])


def _run(fn):
    db=database.SessionLocal()
    try:
        result=fn(db)
        db.commit()
        return result
    except service.FitnessError as error:
        db.rollback()
        raise HTTPException(error.status,error.message) from None
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.get('/exercises')
def exercises():
    return _run(service.list_exercises)


@router.post('/exercises')
def create_exercise(body:schemas.ExerciseCreate):
    return _run(lambda db:service.exercise_dict(service.create_exercise(db,body)))


@router.patch('/exercises/{identity}')
def update_exercise(identity:int,body:schemas.ExercisePatch):
    return _run(lambda db:service.exercise_dict(service.update_exercise(db,identity,body)))


@router.get('/workouts')
def workouts():
    return _run(service.list_workouts)


@router.post('/workouts')
def create_workout(body:schemas.WorkoutCreate):
    return _run(lambda db:service.workout_dict(service.create_workout(db,body)))


@router.get('/workouts/{identity}')
def workout(identity:int):
    return _run(lambda db:service.workout_dict(service.get_workout(db,identity)))


@router.patch('/workouts/{identity}')
def update_workout(identity:int,body:schemas.WorkoutPatch):
    return _run(lambda db:service.workout_dict(service.update_workout(db,identity,body)))


@router.get('/rehab/exercises')
def rehab_exercises():
    return _run(service.list_rehab_exercises)


@router.post('/rehab/exercises')
def create_rehab_exercise(body:schemas.RehabExerciseCreate):
    return _run(lambda db:service.rehab_exercise_dict(service.create_rehab_exercise(db,body)))


@router.patch('/rehab/exercises/{identity}')
def update_rehab_exercise(identity:int,body:schemas.RehabExercisePatch):
    return _run(lambda db:service.rehab_exercise_dict(service.update_rehab_exercise(db,identity,body)))


@router.get('/rehab/sessions')
def rehab_sessions():
    return _run(service.list_rehab_sessions)


@router.post('/rehab/sessions')
def create_rehab_session(body:schemas.RehabSessionCreate):
    return _run(lambda db:service.rehab_session_dict(service.create_rehab_session(db,body)))


@router.get('/rehab/sessions/{identity}')
def rehab_session(identity:int):
    return _run(lambda db:service.rehab_session_dict(service.get_rehab_session(db,identity)))


@router.patch('/rehab/sessions/{identity}')
def update_rehab_session(identity:int,body:schemas.RehabSessionPatch):
    return _run(lambda db:service.rehab_session_dict(service.update_rehab_session(db,identity,body)))


@router.get('/progress')
def progress():
    return _run(service.progress)


@router.get('/exercises/{identity}/progress')
def exercise_progress(identity:int):
    return _run(lambda db:service.exercise_progress(db,identity))
