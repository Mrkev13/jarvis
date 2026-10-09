"""Definitions archive; durable sessions and measurement snapshots never cascade-delete."""
from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from database import Base
from time_utils import utc_now

TYPES = "('strength', 'bodyweight', 'duration', 'distance')"


def measurement_checks(prefix):
    return tuple(CheckConstraint(f'{field} IS NULL OR ({field} {bounds})',name=f'ck_{prefix}_{field}')
                 for field,bounds in [('reps','>= 0 AND reps <= 10000'),('weight_kg','>= 0 AND weight_kg <= 10000'),
                                      ('duration_seconds','> 0 AND duration_seconds <= 604800'),
                                      ('distance_m','> 0 AND distance_m <= 10000000')])


class Exercise(Base):
    __tablename__ = 'fitness_exercises'
    __table_args__ = (CheckConstraint(f'type IN {TYPES}',name='ck_fitness_exercises_type'),)
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    category=Column(String(80),nullable=False,default='general')
    equipment=Column(String(120))
    muscle_group=Column(String(120))
    type=Column(String(20),nullable=False)
    active=Column(Boolean,nullable=False,default=True)
    created_at=Column(DateTime,nullable=False,default=utc_now)
    archived_at=Column(DateTime)


class WorkoutSession(Base):
    __tablename__ = 'fitness_workouts'
    __table_args__ = (CheckConstraint('duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 10080)',name='ck_fitness_workouts_duration'),)
    id=Column(Integer,primary_key=True)
    performed_on=Column(Date,nullable=False,index=True)
    title=Column(String(200))
    notes=Column(Text)
    duration_minutes=Column(Integer)
    source=Column(String(20),nullable=False,default='manual')
    created_at=Column(DateTime,nullable=False,default=utc_now)
    updated_at=Column(DateTime,nullable=False,default=utc_now)
    sets=relationship('WorkoutSet',back_populates='session',order_by='WorkoutSet.order_index',passive_deletes='all')


class WorkoutSet(Base):
    __tablename__ = 'fitness_workout_sets'
    __table_args__ = (UniqueConstraint('workout_session_id','order_index',name='uq_fitness_workout_set_order'),
                     CheckConstraint('order_index >= 0 AND order_index <= 199',name='ck_fitness_workout_set_order'),
                     CheckConstraint('rir IS NULL OR (rir >= 0 AND rir <= 10)',name='ck_fitness_workout_set_rir'),
                     CheckConstraint(f'exercise_type IN {TYPES}',name='ck_fitness_workout_set_type'),
                     *measurement_checks('fitness_workout_set'))
    id=Column(Integer,primary_key=True)
    workout_session_id=Column(Integer,ForeignKey('fitness_workouts.id',ondelete='RESTRICT'),nullable=False,index=True)
    exercise_id=Column(Integer,ForeignKey('fitness_exercises.id',ondelete='RESTRICT'),nullable=False,index=True)
    exercise_name=Column(String(120),nullable=False)
    exercise_type=Column(String(20),nullable=False)
    order_index=Column(Integer,nullable=False)
    reps=Column(Integer)
    weight_kg=Column(Float)
    duration_seconds=Column(Integer)
    distance_m=Column(Float)
    rir=Column(Float)
    completed=Column(Boolean,nullable=False,default=True)
    notes=Column(Text)
    session=relationship('WorkoutSession',back_populates='sets')


class RehabExercise(Base):
    __tablename__ = 'fitness_rehab_exercises'
    __table_args__ = (CheckConstraint(f'type IN {TYPES}',name='ck_fitness_rehab_exercises_type'),)
    id=Column(Integer,primary_key=True)
    name=Column(String(120),nullable=False)
    type=Column(String(20),nullable=False)
    body_area=Column(String(120))
    instructions=Column(Text)
    active=Column(Boolean,nullable=False,default=True)
    created_at=Column(DateTime,nullable=False,default=utc_now)
    archived_at=Column(DateTime)


class RehabSession(Base):
    __tablename__ = 'fitness_rehab_sessions'
    id=Column(Integer,primary_key=True)
    performed_on=Column(Date,nullable=False,index=True)
    notes=Column(Text)
    created_at=Column(DateTime,nullable=False,default=utc_now)
    updated_at=Column(DateTime,nullable=False,default=utc_now)
    entries=relationship('RehabEntry',back_populates='session',order_by='RehabEntry.order_index',passive_deletes='all')


class RehabEntry(Base):
    __tablename__ = 'fitness_rehab_entries'
    __table_args__ = (UniqueConstraint('rehab_session_id','order_index',name='uq_fitness_rehab_entry_order'),
                     CheckConstraint('order_index >= 0 AND order_index <= 199',name='ck_fitness_rehab_entry_order'),
                     CheckConstraint('sets >= 1 AND sets <= 100',name='ck_fitness_rehab_entry_sets'),
                     CheckConstraint('pain_before IS NULL OR (pain_before >= 0 AND pain_before <= 10)',name='ck_fitness_rehab_entry_pain_before'),
                     CheckConstraint('pain_after IS NULL OR (pain_after >= 0 AND pain_after <= 10)',name='ck_fitness_rehab_entry_pain_after'),
                     CheckConstraint(f'exercise_type IN {TYPES}',name='ck_fitness_rehab_entry_type'),
                     *measurement_checks('fitness_rehab_entry'))
    id=Column(Integer,primary_key=True)
    rehab_session_id=Column(Integer,ForeignKey('fitness_rehab_sessions.id',ondelete='RESTRICT'),nullable=False,index=True)
    rehab_exercise_id=Column(Integer,ForeignKey('fitness_rehab_exercises.id',ondelete='RESTRICT'),nullable=False,index=True)
    exercise_name=Column(String(120),nullable=False)
    exercise_type=Column(String(20),nullable=False)
    order_index=Column(Integer,nullable=False)
    sets=Column(Integer,nullable=False,default=1)
    reps=Column(Integer)
    weight_kg=Column(Float)
    duration_seconds=Column(Integer)
    distance_m=Column(Float)
    pain_before=Column(Float)
    pain_after=Column(Float)
    notes=Column(Text)
    session=relationship('RehabSession',back_populates='entries')
