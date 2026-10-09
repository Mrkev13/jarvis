"""Explicit bounded write contracts; no medical interpretation or implicit units."""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

ExerciseType = Literal['strength', 'bodyweight', 'duration', 'distance']
Id = Annotated[StrictInt, Field(gt=0)]
Order = Annotated[StrictInt, Field(ge=0, le=199)]
Reps = Annotated[StrictInt, Field(ge=0, le=10000)]
PositiveSeconds = Annotated[StrictInt, Field(gt=0, le=604800)]
Weight = Annotated[float, Field(ge=0, le=10000, allow_inf_nan=False)]
Distance = Annotated[float, Field(gt=0, le=10000000, allow_inf_nan=False)]
Scale = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)]
Name = Annotated[str, Field(min_length=1,max_length=120)]
Note = Annotated[str, Field(max_length=2000)]


class WriteModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ExerciseCreate(WriteModel):
    name: Name
    type: ExerciseType = 'strength'
    category: Annotated[str,Field(max_length=80)] = 'general'
    equipment: Annotated[str,Field(max_length=120)] | None = None
    muscle_group: Annotated[str,Field(max_length=120)] | None = None


class ExercisePatch(WriteModel):
    name: Name | None = None
    type: ExerciseType | None = None
    category: Annotated[str,Field(max_length=80)] | None = None
    equipment: Annotated[str,Field(max_length=120)] | None = None
    muscle_group: Annotated[str,Field(max_length=120)] | None = None
    active: StrictBool | None = None


class Measurements(WriteModel):
    reps: Reps | None = None
    weight_kg: Weight | None = None
    duration_seconds: PositiveSeconds | None = None
    distance_m: Distance | None = None


class WorkoutSetWrite(Measurements):
    exercise_id: Id
    order_index: Order
    rir: Scale | None = None
    completed: StrictBool = True
    notes: Annotated[str,Field(max_length=500)] | None = None


class WorkoutCreate(WriteModel):
    performed_on: date
    title: Annotated[str,Field(max_length=200)] | None = None
    notes: Note | None = None
    duration_minutes: Annotated[StrictInt,Field(gt=0,le=10080)] | None = None
    sets: Annotated[list[WorkoutSetWrite],Field(min_length=1,max_length=200)]


class WorkoutPatch(WriteModel):
    performed_on: date | None = None
    title: Annotated[str,Field(max_length=200)] | None = None
    notes: Note | None = None
    duration_minutes: Annotated[StrictInt,Field(gt=0,le=10080)] | None = None


class RehabExerciseCreate(WriteModel):
    name: Name
    type: ExerciseType = 'bodyweight'
    body_area: Annotated[str,Field(max_length=120)] | None = None
    instructions: Note | None = None


class RehabExercisePatch(WriteModel):
    name: Name | None = None
    type: ExerciseType | None = None
    body_area: Annotated[str,Field(max_length=120)] | None = None
    instructions: Note | None = None
    active: StrictBool | None = None


class RehabEntryWrite(Measurements):
    rehab_exercise_id: Id
    order_index: Order
    sets: Annotated[StrictInt,Field(ge=1,le=100)] = 1
    pain_before: Scale | None = None
    pain_after: Scale | None = None
    notes: Annotated[str,Field(max_length=500)] | None = None


class RehabSessionCreate(WriteModel):
    performed_on: date
    notes: Note | None = None
    entries: Annotated[list[RehabEntryWrite],Field(min_length=1,max_length=200)]


class RehabSessionPatch(WriteModel):
    performed_on: date | None = None
    notes: Note | None = None
