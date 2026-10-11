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
- File URLs must match the configured origin exactly (scheme, case-insensitive host, effective port – an explicit
  `:443` equals the default) and lie under that install's own `…/webservice/pluginfile.php/` (a Moodle in a
  sub-path is supported). Userinfo, backslashes, control/space characters and encoded `.`/`/` (`%2e`, `%2f`) are
  rejected; the request is rebuilt from the configured origin, never the upstream host. No user-supplied URL exists.
- Redirects are refused; TLS is verified; every read is bounded to `limit + 1` bytes whatever Content-Length says.
- Every transport/JSON exception is discarded (raised fresh outside the `except` block, so no `__context__` chain
  carries the upstream error) and replaced with an allowlisted category
  (`not_configured`, `unavailable`, `auth_failed`, `ws_error`, `response_invalid`, …). The module never logs.
- Tests plant canary token/URL values and assert they appear in none of the persisted rows, API responses,
  `/changes`, `/activity`, logs or rendered exceptions (`backend/tests/test_study_materials.py`).

## Data model (migration `0021_study_materials`)

- `study_courses`: `(source, external_id)` unique, `source IN ('moodle', 'moodle_export')` (the second value since
  migration `0023_study_course_export_source`, see "ZIP import fallback"); `name`, `short_name`;
  **`subject_id` = manual mapping** (nullable, `ON DELETE SET NULL`). Neither a sync nor an import sets or changes it.
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
filesystem). Writes go to a unique temp file and are renamed atomically. Macro-enabled OOXML (`vbaProject.bin`) is
rejected.

**Blob lifecycle:** a changed file updates the same row and points it at a new blob; the previous blob stays on disk
(it may still be referenced by an identical file elsewhere, and history is never deleted). A blob written in a
course transaction that later rolls back is likewise left unreferenced. There is no blob garbage collection yet –
unreferenced files are harmless and can be removed by a future maintenance task. The download endpoint serves only that regex-validated name with `Content-Disposition: attachment`,
`nosniff` and `no-store`. Nothing is executed or rendered.

## Extraction

Local and bounded: pypdf 6.19 (≤ 300 pages; 6.x carries the decompression/DoS fixes missing in 5.x), PPTX/DOCX XML parts read in memory (DOCTYPE/entities refused, part sizes
capped, any DTD/entity declaration refused by an encoding-independent expat pre-scan), TXT as UTF-8; max 200 000 characters. Failure → `extraction_status = failed`, the binary stays.
Documents are **never sent to Groq** or any other service.

## Integrations (Module Framework, owner = School)

- Search: `SearchSource('school_materials')` – title, file name, section, course and a bounded text excerpt.
- AI context: `ContextSection('school_materials')` – counts by type, missing count and recent titles; never text.
  Targeted retrieval of document passages for Jarvis is future work.
- Domain events `school.material.{created,updated,source_missing,restored}` (payload: ids, type, download status,
  changed field names – no titles or text), each with one Activity row; What Changed via the School `ChangeSource`.
- REST: `GET /school/materials` (filters `subject_id`, `course_id`, `type`, `state=active|missing|all`),
  `GET /school/materials/{id}` (adds a 3 000-char excerpt), `GET /school/materials/{id}/file`,
  `PUT /school/materials/courses/{id}` (manual mapping), `POST /school/materials/sync`.
- UI: `/school/materials` (filters subject/type/state, missing state, course→subject mapping, download).

Course→subject suggestion: only when exactly one subject's code (≥ 3 chars) equals a whole token of the course
short/full name. Never by name similarity, never applied automatically.

## Targeted reading (MRK-44)

Jarvis can inspect **one** material on demand; documents are never pushed wholesale into AI requests.

- Service `modules/school/reading.py`, by DB id only (never a file name or path); returns metadata, an explicit
  `text_status` (`available | empty | failed | unsupported | not_downloaded`) and bounded chunks. Source-missing
  materials stay readable from stored text (`material.state = source_missing`).
- **Chunking:** units = PPTX slides (`[n]` lines), PDF pages (page-marker lines written by extraction since MRK-44 –
  older extractions have none, so no page numbers are invented), else paragraphs/lines; packed to ≈ 900 chars,
  never above 1 500, never across two slides/pages; oversized units split at sentence then word boundaries.
- **Ranking (with `q`):** folded tokens minus stopwords; a term matches a word equal to it or starting with its stem
  (first max(4, len−3) chars – light Czech inflection); score = Σ(1 + 0.25·min(extra hits, 4)) + 2 per adjacent
  query-term pair adjacent in the chunk; ties → document order; zero score is not returned (explicit no-match).
  Without `q`: the beginning plus an outline (slides/pages only).
- **Caps:** default 3 chunks / 4 000 chars, hard max 8 / 8 000; query ≤ 200 chars, ≤ 12 terms.
- **API:** `GET /school/materials/{id}/content?q=&max_chunks=&max_chars=` (auth + School gate, 422 above caps).
- **AI tools** (`tool_registry`, read-only, no confirmation): `get_study_materials` (ids/metadata by topic or
  subject, no text) and `get_study_material_text` (bounded excerpts of one material, with a notice that excerpts are
  quoted data, not instructions). Routed only for study questions (area `school_materials`); the School gate is
  also checked at call time. The AI context lists recent materials with their ids.
- **UI:** the selected material on `/school/materials` shows its text state, a bounded preview with page/slide
  labels, an outline and a "find in material" box (`?material=ID&find=…` deep link).
- No embeddings, vector DB, OCR or automatic summaries; no extra tables (no migration).

Future RAG boundary: `extracted_text` is the derived, rebuildable input for later chunking/embedding; no vector DB yet.

Status split: **the code foundation is merged; the real ČZU connector is NOT verified** – tracked separately.

## ZIP import fallback (MRK-56)

**Official Moodle Web Services remain the primary integration.** When the site does not give students a web-service
token, materials can still reach the Hub by a manual transport: the official Moodle feature **„Stáhnout obsah kurzu"**
(*Download course content*) produces one ZIP per course, which is imported by the same core – no token, no HTML
scraping, no login automation.

**One shared core.** `modules/school/zip_import.py` validates the archive, turns it into the MRK-42
`CourseSnapshot`/`RemoteFile` model and applies it with `service._sync_course`: the same `study_courses` /
`study_materials` tables and identity scheme (`"<activity id>:<path><file name>"`), the same download policy (type
allowlist, `MOODLE_MAX_FILE_MB`, signature sniffing, macro-package rejection), content-addressed storage, extraction,
domain events (`school.material.*`, Activity context `moodle_zip_import`), Search, What Changed and AI metadata.

| Rule | Behaviour |
|---|---|
| Source | Courses are stored with `source = 'moodle_export'`; Web Services rows keep `source = 'moodle'`. |
| Identity | The export's own folder numbers (course folder, activity folders). **They are not assumed to equal Moodle API ids** – on a real export the course id linked from the export index differed from the folder number – so the two sources never share a row and no seamless reconciliation with a later Web Services sync is claimed. |
| Presence | A course ZIP is **not a provably complete snapshot** (Moodle leaves out files above its download limit and items it cannot export; folder activities may come without files). An import therefore only **adds/updates**; it never sets `source_missing_at`. Files listed in an activity page but absent from the ZIP become `metadata_only` rows. |
| Content | Only **PDF / PPTX / DOCX / TXT** are stored and extracted. Other files inside an activity are recorded as `unsupported` metadata. |
| HTML | The export's `index.html` pages are parsed locally (bounded, stdlib parser, no network) for the course name, section headings and full activity titles only. HTML never becomes a material, Search hit or AI context. |
| Idempotency | Export timestamps are the export time, so changes are detected by **content sha256**: re-importing the same ZIP writes, downloads and emits nothing; a changed file updates its row; the binary is stored once per checksum. |
| Mapping | Course → subject stays manual; the exact-code suggestion uses the course codes found in the export folder name. |

**Using it.**

- UI: `/school/materials` → **Importovat ZIP z Moodle** → pick the `.zip`. The page shows a short summary (new /
  changed / unchanged, unsupported, missing from the ZIP) or a safe Czech error, then reloads the list.
  API: `POST /school/materials/import-zip`, the raw ZIP as the request body (`Content-Type: application/zip`);
  errors are allowlisted categories only (`archive_invalid`, `not_course_export`, `unsafe_path`, …).
- Folder: a thin wrapper over the same service imports every `*.zip` directly in a folder (not recursive):

  ```
  cd backend
  python scripts/import_moodle_zips.py <folder with exported ZIPs> --env-file <protected production env file>
  ```

  It prints only file names and counts and exits non-zero if any archive was rejected. It is a one-shot CLI, not a
  server or scheduler.

**Archive safety.** The whole archive is validated before anything is read, and rejected on: absolute paths, drive
letters, backslashes, `.`/`..`/empty path segments, control characters, over-long names, symlink entries, encrypted
entries, exact duplicate names (case variants are distinct files), more than 5000 entries, more than 4 GiB declared uncompressed in total,
or an entry above 1 MiB compressed more than 200×. The upload is streamed with a hard cap (`MOODLE_ZIP_MAX_MB`,
default 512) into a spooled temp file that is deleted afterwards. Entries are read in memory with hard byte caps
(HTML ≤ 1 MB per page and 64 MB per import – beyond that folder names are used; files ≤ `MOODLE_MAX_FILE_MB`)
whatever their headers claim; a corrupt or unreadable entry (bad CRC, unsupported compression) is a per-file
`failed`, never a failed import. At most 200 listed-but-absent links per activity become `metadata_only` rows and
at most 5000 files are accepted per import (`too_many_entries`), which bounds rows, events and Activity per upload.
Nothing is extracted to disk and nested archives are never opened. One import is one transaction: a failure rolls
back everything.

**Tests and data.** `backend/tests/test_moodle_zip_import.py` builds synthetic exports in memory (invented course,
generated documents). **No real Moodle export, file or extracted text belongs in git.**

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
