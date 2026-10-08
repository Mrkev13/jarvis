# MRK-25 Off-machine Backup Copy and Restore Drill Design

## Objective

Add a provider-independent, locally testable foundation that copies only completed Standa Hub backup runs to an offsite target, applies optional mandatory encryption, performs deterministic grandfather-father-son retention, and verifies a retrieved copy in scratch space. The implementation must not mutate the source backup tree, production database, or production media directory.

## Existing backup contract

`backup_service.run_backup()` writes a schema-version-1 run JSON under `BACKUP_DIR/runs`. A successful run references, using paths relative to `BACKUP_DIR`:

- one gzip-compressed PostgreSQL plain SQL dump or SQLite copy;
- one media manifest and its SHA-256;
- immutable media archive entries named by the media manifest, each with size and SHA-256.

Only `status: success` runs with valid relative paths and verified checksums are eligible for offsite transfer. Failed, incomplete, malformed, or escaping references fail verification and are never published as completed offsite runs.

## Artifact and provider model

The source run is materialized in a temporary staging directory as a self-contained snapshot containing the source run JSON, database dump, media manifest, and every media payload referenced by the manifest. The source files are opened read-only and are never moved or deleted.

The staged snapshot becomes a deterministic TAR payload. TAR members use normalized relative POSIX paths. A separate safe offsite metadata document contains only:

- run ID and UTC run time;
- source backup identifier;
- encrypted yes/no;
- transfer completion;
- checksum result;
- logical offsite target identifier.

The provider interface supports storing a completed run, listing completed runs, retrieving a run to caller-owned scratch space, and deleting a named expired run. Providers receive an opaque payload plus safe metadata; they do not interpret backup contents.

`LocalFilesystemOffsiteTarget` is the only provider implemented now. Each run has its own directory. Publication uses a unique temporary directory, an exclusive destination reservation, payload and metadata writes, and a completion marker written last. Listing returns only valid completed entries. An existing run ID is never overwritten. Cleanup is restricted to validated run IDs below the configured provider root.

Future S3, Backblaze B2, Google Drive, and OneDrive providers can implement the same opaque-object contract without changing packaging, retention, encryption, or verification policy.

## Encryption

An encryption adapter transforms the TAR payload to an encrypted opaque payload and can decrypt a retrieved copy. It has an explicit availability check and never returns or logs key material.

The production adapter supports `age` recipient encryption when the executable and caller-supplied recipient/identity configuration are available. Key material and identity paths are runtime inputs and are not stored in offsite metadata. Tests use a deterministic fake encryptor.

When encryption is required, a missing/unavailable adapter, failed encryption, or missing decrypt capability fails closed before a completed offsite run is published. Unencrypted mode is explicit. OpenSSL detected on the current machine is not selected automatically because no approved passphrase/key-management contract exists. No global tools are installed.

## Retention

Retention consumes provider-neutral completed-run descriptors with timezone-aware UTC instants. Calendar bucketing uses an explicit `ZoneInfo` timezone, defaulting to `Europe/Prague` to match Standa Hub scheduling.

For valid completed runs sorted newest first, the planner retains:

- the newest run in each of the 14 newest distinct local calendar-day buckets;
- the newest run in each of the 8 newest distinct local ISO-week buckets;
- the newest run in each of the 12 newest distinct local calendar-month buckets;
- the newest valid completed run unconditionally.

The sets are unioned and deduplicated by run ID. Invalid/incomplete runs are excluded from automatic deletion and reported separately. Dry-run returns the exact deterministic keep/delete plan without calling provider deletion. Cleanup continues through individual failures and returns a structured cleanup-failure outcome without hiding partial results.

Boundary tests cover multiple runs per bucket, ISO year boundaries, month/year boundaries, timezone conversion near local midnight, duplicate qualification across tiers, and unconditional newest preservation.

## Scratch-only restore verification

Verification asks the provider to retrieve a copy into a newly created temporary directory. If encrypted, the configured adapter decrypts the copy there. The TAR is inspected before extraction and rejects:

- absolute member names;
- `..` traversal or any resolved escape outside scratch;
- symbolic links, hard links, devices, FIFOs, and other non-regular/non-directory members.

Only regular files and directories are extracted. The verifier then validates the copied run JSON, database dump existence/size/SHA-256, media manifest existence/SHA-256, and every referenced media payload size/SHA-256. All paths are relative and resolved beneath the extracted snapshot root. Missing DB/media files and corruption produce structured failures.

The workflow never points database tools at the production database and never writes into the production media directory. A real scratch PostgreSQL restore is deferred because `psql`, `createdb`, `dropdb`, and `pg_restore` are not available in the current environment. The local acceptance drill is therefore an end-to-end integrity restore of a retrieved copy.

## Status contract

Operations return a structured result with operation, success flag, run ID, safe outcome code, UTC timestamps, and allowlisted measurements. Required outcome categories cover:

- local backup/source validation failure;
- encryption failure;
- offsite transfer failure;
- verification failure;
- retention cleanup failure.

Raw exception strings, credentials, environment values, absolute paths, and provider connection details are excluded. MRK-26 can later map these results to monitoring observations, while MRK-23 can expose allowlisted health fields. This issue does not wire notifications, scheduling, or `/health`.

## Testing and safety

All new tests use temporary source, target, and scratch directories. Tests cover successful copy, source immutability, encryption-required fail-closed behavior, retention boundaries, newest preservation, restore verification, corruption, missing DB/media, transfer failure, cleanup failure, secret canaries, and malicious TAR paths/links.

The existing ignored local backup sample is inspected read-only to confirm format compatibility. No cloud upload, production restore, schema/data mutation, or Groq request is allowed.
