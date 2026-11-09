# School: credit status, exam results and weekly attendance (MRK-86)

Manual, per subject, no timetable (per-lesson attendance needs MRK-41) and no UIS connection.

## Data (migration `0028_school_progress`, additive)

- `subjects.credit_status` – `pending` | `passed` | `failed` (NULL = pending, "nesplněn"), `subjects.credit_date`
  (set for passed/failed, default today in Europe/Prague, never in the future), `subjects.absence_limit` (optional
  number of allowed absences, 0–52, NULL = no limit).
- `school_attendance` – one row per subject and week: `week_start` (Monday, Europe/Prague) and `present`
  (byl / nebyl). A week without a row is "not recorded" and counts neither way. Unique `(subject_id, week_start)`.

## Rules (deterministic, `backend/modules/school/progress.py`)

- Attendance can be written only for an active subject and only up to the current week; writing the same value is a
  no-op; `present: null` removes the row. Every write is an Activity entry (same transaction).
- Credit status change = domain event `school.subject.credit_changed` with an Activity projection.
- Absences: `remaining = limit − absent`. Level `last` (1 left), `exhausted` (0 left), `exceeded` (< 0). Those
  levels show in Dnes → Pozornost (and so in "Co hoří" on the Control Center) as `subject:<id>` items –
  `warning`, or `important` when exceeded – unless the credit is already passed.
- Exam summary: open / closed / passed / failed counts and the latest closed exams with their result.

## API

- `GET /school/progress[?include_archived=true]` – overview per subject (`credit`, `exams`, `attendance` with
  `this_week`, last 16 recorded weeks, `text`, `level`, `warning`), plus `week_start` / `previous_week_start`.
- `PUT /school/subject/{id}/credit` `{status, date?}`
- `PUT /school/subject/{id}/attendance` `{week_start, present: true | false | null}`
- `PATCH /school/subject/{id}` `{absence_limit: n | null}` (MRK-75 endpoint, plain `school.subject.updated`).

## AI

The School context section (keywords include `zapoct`, `dochaz`, `absenc`) gets computed lines only:
"Zápočty: …", "Docházka (týdny): Předmět: byl 5 z 6, absence 1 z max. 2 (zbývá poslední)" and
"Varování absencí: …". The LLM never counts anything and never sees attendance rows.

## UI

`/school` → section "Zápočty a docházka": per active subject the credit status (change in one select), exam
summary, attendance "X z Y" and absences, and for the current week two buttons Byl / Nebyl (one tap, ≥ 44 px);
the previous week can be corrected from the same card.
