# Moodle Content Sync – study materials (MRK-42)

ICS (docs/calendar.md) answers **when**. Content sync answers **what to study**: it discovers the files in your
Moodle courses (presentations, PDFs, documents), keeps a durable index of them in Standa Hub and stores a local copy
of the allowed types, so Jarvis can later study from them.

Status: **provider-neutral foundation + official Moodle Web Services adapter, verified only against synthetic
responses.** Nothing in this document has been verified against the real ČZU Moodle yet (see the end).

## Mechanism (feasibility)

| Option | Decision |
|---|---|
| Moodle Web Services, REST protocol, JSON (`/webservice/rest/server.php`) | **Used.** Official, documented, the same API the Moodle mobile app uses. |
| `core_webservice_get_site_info` → `core_enrol_get_users_courses` → `core_course_get_contents` | Own user id → enrolled courses → sections/modules/files (`type: file`, `filename`, `filepath`, `filesize`, `fileurl`, `timemodified`, `mimetype`). |
| File download from the returned `fileurl` (`/webservice/pluginfile.php/...`) | **Used**, token sent in the POST body, never in the URL. |
| HTML scraping / browser-automation login / username+password token exchange | **Not implemented** (brittle; would need the user's password). |

The token is the user's personal web-service token (Moodle → Preferences → Security keys, or one issued by the site).
Whether ČZU exposes it is unknown – see "Needs real verification".

## Configuration (backend only)

```
MOODLE_WS_BASE_URL=https://<moodle host>   # HTTPS only, no credentials/query in it
MOODLE_WS_TOKEN=<token>                     # secret – .env only
MOODLE_MAX_FILE_MB=25                       # 1–100
MOODLE_COURSE_IDS=                          # optional allowlist of course ids
```

The frontend only ever receives `configured: true/false`. Sync is manual (`POST /school/materials/sync`); no scheduler.

## Secret model

Never stored or emitted anywhere (DB, API response, frontend, logs, Activity, domain events, What Changed, exception
text): the token, the base URL with any secret, signed or private file URLs, upstream authorization data.

- The token travels only in POST bodies; file URLs are reduced to `scheme://host/path` (any returned query with a
  signature/token is dropped) and accepted only on the configured origin under `/webservice/pluginfile.php/`.
- Redirects are refused; TLS is verified; responses are size-capped.
- Every transport/JSON exception is discarded and replaced with an allowlisted category
  (`not_configured`, `unavailable`, `auth_failed`, `ws_error`, `response_invalid`, …). The module never logs.
- Tests plant canary token/URL values and assert they appear in none of the persisted rows, API responses,
  `/changes`, `/activity`, logs or rendered exceptions (`backend/tests/test_study_materials.py`).

## Data model (migration `0021_study_materials`)

- `study_courses`: `(source='moodle', external_id)` unique; `name`, `short_name`; **`subject_id` = manual mapping**
  (nullable, `ON DELETE SET NULL`). A sync never sets or changes it.
- `study_materials`: unique `(course_id, external_id)` where `external_id = "<course module id>:<filepath><filename>"`
  (sha256 when too long). Metadata (title, section, file name, type, mime, size, modified time), download outcome
  (`stored | metadata_only | too_large | unsupported | rejected | failed`), content-addressed `stored_name` +
  `checksum` (sha256), derived `extracted_text` + `extraction_status`, and `source_missing_at`.

## Sync semantics

- Per course: one `core_course_get_contents` call = a **complete snapshot** of that course's file resources
  (`resource` and `folder` activities only – no quizzes, grades, forums, messages, assignments).
- Each course is its own transaction under a row lock; any error rolls the whole course back. Course discovery
  failure aborts the sync with nothing written.
- Unchanged file (same size + modified time, binary present) → no download, no write.
- Changed file → same row updated, re-downloaded, re-extracted; one `school.material.updated`.
- Absent from a complete snapshot → `source_missing_at` set (never deleted, binary kept); reappearing → same row
  restored. A failed course, a malformed module/section (uncertain) or a malformed course snapshot never hides anything.
- Duplicate entries in one snapshot are collapsed; identical binaries are stored once.

## Download policy

Allowlist PDF, PPTX, DOCX, TXT (by extension) **and** a byte-signature check (`%PDF-`, OOXML zip with the right main
part, UTF-8 text without NUL). Size cap before and during download. Anything else is metadata-only. Files live in
`MEDIA_DIR/study-materials/<sha256>.<ext>`; names come from the content only (no upstream name ever reaches the
filesystem). The download endpoint serves only that regex-validated name with `Content-Disposition: attachment`,
`nosniff` and `no-store`. Nothing is executed or rendered.

## Extraction

Local and bounded: pypdf (≤ 300 pages), PPTX/DOCX XML parts read in memory (DOCTYPE/entities refused, part sizes
capped), TXT as UTF-8; max 200 000 characters. Failure → `extraction_status = failed`, the binary stays.
Documents are **never sent to Groq** or any other service.

## Integrations (Module Framework, owner = School)

- Search: `SearchSource('school_materials')` – title, file name, section, course and a bounded text excerpt.
- AI context: `ContextSection('school_materials')` – counts by type, missing count and recent titles; never text.
- Domain events `school.material.{created,updated,source_missing,restored}` (payload: ids, type, download status,
  changed field names – no titles or text), each with one Activity row; What Changed via the School `ChangeSource`.
- REST: `GET /school/materials` (filters `subject_id`, `course_id`, `type`, `state=active|missing|all`),
  `GET /school/materials/{id}` (adds a 3 000-char excerpt), `GET /school/materials/{id}/file`,
  `PUT /school/materials/courses/{id}` (manual mapping), `POST /school/materials/sync`.
- UI: `/school/materials` (filters subject/type/state, missing state, course→subject mapping, download).

Course→subject suggestion: only when exactly one subject's code (≥ 3 chars) equals a whole token of the course
short/full name. Never by name similarity, never applied automatically.

Future RAG boundary: `extracted_text` is the derived, rebuildable input for later chunking/embedding; no vector DB yet.

## Needs real verification (not done – cloud session, synthetic fixtures only)

1. Does ČZU Moodle enable web services / the mobile service, and can a student create a personal token?
2. Which functions the token's service allows (`core_enrol_get_users_courses`, `core_course_get_contents`).
3. Real course discovery (hidden/past courses, course count, `MOODLE_COURSE_IDS` need).
4. Real `core_course_get_contents` structure: resources vs folders, `uservisible`, `contents` presence,
   `timemodified`, `filesize`, mimetypes, files embedded elsewhere (pages, labels, assignments are not synced).
5. Real downloads via `webservice/pluginfile.php` with the token in the POST body (vs `?token=`), error bodies,
   redirects (refused here), typical file sizes vs `MOODLE_MAX_FILE_MB`.
6. Extraction quality on real slides/scans (scanned PDFs have no text – OCR is out of scope).
7. Windows paths for `MEDIA_DIR/study-materials` on the real host.
