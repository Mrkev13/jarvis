# School: credit status, exam results and weekly attendance (MRK-86)

Manual, per subject, no timetable (per-lesson attendance needs MRK-41) and no UIS connection.

## Data (migration `0028_school_progress`, additive)

- `subjects.credit_status` – `pending` | `passed` | `failed` (NULL = pending, "nesplněn"), `subjects.credit_date`
  (set for passed/failed, default today in Europe/Prague, never in the future), `subjects.absence_limit` (optional
  number of allowed absences, 0–52, NULL = no limit).
- `school_attendance` – one row per subject and week: `week_start` (Monday, Europe/Prague) and `present`
  (byl / nebyl). A week without a row is "not recorded" and counts neither way. Unique `(subject_id, week_start)`.
- MRK-112 (migration `0029_attendance_schedule`, additive): `subjects.attendance_every` (NULL / 1 = every week,
  2 = every other week) and `subjects.attendance_anchor` (a Monday of a class week, only for 2).

## Rules (deterministic, `backend/modules/school/progress.py`)

- Attendance can be written only for an active subject and only up to the current week, any past week included;
  writing the same value is a no-op; `present: null` removes the row. Every write is an Activity entry (same
  transaction).
- Class weeks (MRK-112): a biweekly subject has class in weeks an even number of weeks from its anchor (also before
  it). Only class weeks count and can be written (`422 no_class_week` otherwise; deleting a row is always allowed).
  A row recorded in a non-class week (e.g. before the rhythm was set) stays in the DB but does not count.
- Credit status change = domain event `school.subject.credit_changed` with an Activity projection.
- Absences: `remaining = limit − absent`. Level `last` (1 left), `exhausted` (0 left), `exceeded` (< 0). Those
  levels show in Dnes → Pozornost (and so in "Co hoří" on the Control Center) as `subject:<id>` items –
  `warning`, or `important` when exceeded – unless the credit is already passed.
- Exam summary: open / closed / passed / failed counts and the latest closed exams with their result.

## API

- `GET /school/progress[?include_archived=true]` – overview per subject (`credit`, `exams`, `attendance` with
  `this_week`, recorded class weeks within the offered range, `class_weeks` = class weeks of the last 26 calendar
  weeks newest first, `class_this_week`, `text`, `level`, `warning`; `schedule` `{every, anchor}`), plus
  `week_start` / `previous_week_start`.
- `PUT /school/subject/{id}/credit` `{status, date?}`
- `PUT /school/subject/{id}/attendance` `{week_start, present: true | false | null}`
- `PATCH /school/subject/{id}` `{absence_limit: n | null}` and `{attendance_every: 1 | 2, attendance_anchor: Monday}`
  (MRK-75 endpoint, plain `school.subject.updated`; every other week needs an anchor, every week clears it).

## AI

The School context section (keywords include `zapoct`, `dochaz`, `absenc`) gets computed lines only:
"Zápočty: …", "Docházka (týdny): Předmět: byl 5 z 6, absence 1 z max. 2 (zbývá poslední)" and
"Varování absencí: …". The LLM never counts anything and never sees attendance rows.

## UI

`/school` → section "Zápočty a docházka": per active subject the credit status (change in one select), exam
summary, attendance "X z Y" and absences, and for the current week two buttons Byl / Nebyl (one tap, ≥ 44 px);
the previous week can be corrected from the same card.

MRK-112: select "Výuka" – Každý týden / Ob týden – výuka tento týden / Ob týden – výuka minulý týden (sets the
anchor). A biweekly subject shows "Tento týden · výuka není" in an off week and "Minulá výuka" instead of "Minulý
týden". "Starší týdny" (collapsed, with the count of unrecorded weeks) lists older class weeks with Byl / Nebyl, 8 at
a time ("Zobrazit starší").
