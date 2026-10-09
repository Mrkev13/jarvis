# MRK-33 Fitness & Rehab implementation plan

Goal: durable manual workout and rehab history through the normal module framework.
Base: 68d1df1; current Alembic head 0020_calendar_source_presence. New linear revision 0021_fitness.

Design: six tables (Exercise, WorkoutSession, WorkoutSet, RehabExercise, RehabSession, RehabEntry).
Sessions use performed_on (Prague calendar DATE), not an invented start instant. All records are logged
facts; no future planned rows or automatic Calendar occupation. Exercise type is strength/bodyweight/
duration/distance; kg, reps, seconds and metres have explicit deterministic bounds. Rehab pain is optional
0–10 self-reported tracking only. Definitions archive/restore; no delete endpoints or destructive cascades.
Child rows preserve definition name/type snapshots. Session metadata updates retain prior values in Activity;
set/entry corrections are deliberately deferred rather than destructively replacing history.

Execution and file ownership:
- Backend models/schemas/services/router in backend/modules/fitness; 0021_fitness migration, model registration.
- Backend providers: Search, What Changed, bounded AI context, Today completed facts (no clock times).
  Registry declares implemented capabilities and safe event types. No central aggregator changes.
- Frontend standalone /fitness with exercises, workouts/detail and rehab tabs, using shared UI/API components;
  frontend manifest/registry mirror backend. Frontend development can proceed independently against the
  response contract below; backend owns transactional validation, never inferred from frontend checks.
- Tests first: atomic multi-entry saves, archive/history, type/number validation, metadata edit audit,
  domain-event count/rollback, provider dedupe/disable, bounded eager-loading query count.
- Verify focused/full backend, frontend test/lint/typecheck/build; SQLite/PostgreSQL scratch upgrade →
  downgrade -1 → upgrade + schema parity; synthetic desktop/mobile UI capture and independent code review.
- Commit/push dedicated branch, open PR if API permits, no merge. Linear In Review only if available.

API contract:
GET /fitness/exercises -> {exercises:[definition]}; POST -> definition; PATCH /{id} accepts metadata,
active bool (archive/restore); type change with existing history is rejected.
Exercise definition: id,name,category,equipment,muscle_group,type,active,created_at,archived_at.
GET /fitness/workouts -> {workouts:[session]}; GET /{id} -> session; POST full session; PATCH metadata only.
Workout: id,performed_on,title,notes,duration_minutes,source,created_at,updated_at,sets:[...].
Set: id,exercise_id,exercise_name,exercise_type,order_index,reps,weight_kg,duration_seconds,distance_m,rir,completed,notes.
POST accepts performed_on,title?,notes?,duration_minutes?,sets:[{exercise_id,order_index,...measurements}].
GET/POST/PATCH /fitness/rehab/exercises parallel definitions: id,name,type,body_area,instructions,active,...
GET /fitness/rehab/sessions -> {sessions:[...]}; GET/PATCH /{id}, POST multi-entry session.
RehabSession: id,performed_on,notes,created_at,updated_at,entries:[{id,rehab_exercise_id,exercise_name,
exercise_type,order_index,sets,reps,weight_kg,duration_seconds,distance_m,pain_before,pain_after,notes}].
GET /fitness/progress -> {week_start,week_workouts,week_rehab_sessions,recent_workouts,recent_rehab_sessions}.
GET /fitness/exercises/{id}/progress -> {exercise_id,last_performed_on,last_sets:[...],recent_sessions:[...]};
last values use completed sets only. All outputs bounded; historical archived definitions remain readable.
