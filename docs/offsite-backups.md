# Off-machine backup copies (MRK-25)

`backend/offsite_backup.py` turns one completed local backup run into a self-contained, verifiable artifact. It is deliberately separate from backup scheduling, notifications and `/health`: callers decide when to invoke it and persist only the returned safe status.

## Data flow

1. Validate a schema-version-1 `runs/backup_<run-id>.json` with `status: success`.
2. Resolve every DB, manifest and media reference beneath `BACKUP_DIR`; reject absolute or escaping paths.
3. Verify the declared size and SHA-256 of the DB dump, media manifest and every referenced media file.
4. Build a deterministic TAR in temporary scratch space. The source backup remains read-only.
5. If encryption is required, encrypt the whole TAR before publication. Missing encryption fails closed.
6. Publish the opaque payload and safe metadata through an offsite target. A completion marker is written last.
7. Retrieve into a new scratch directory for restore verification; never extract into `BACKUP_DIR` or `MEDIA_DIR`.

The offsite TAR keeps the existing relative layout (`runs/`, the DB dump name, `media/manifests/` and referenced `media/archive/` objects), so the existing run and media manifests remain the single integrity contract.

## Provider interface

An offsite target implements:

- `store_run(payload, metadata)` — publish one immutable completed run;
- `list_runs()` — return completed run descriptors;
- `retrieve_run(run_id, destination)` — copy the opaque artifact to caller-owned scratch space;
- `delete_run(run_id)` — remove one explicitly selected expired run.

`LocalFilesystemOffsiteTarget` is the first implementation. Its root contains one directory per validated portable run ID, `payload.tar` or `payload.age`, `metadata.json`, and an empty `complete` marker. It writes and fsyncs files under a unique `.staging-<run-id>-<uuid>` directory, writes/fsyncs the marker last, then renames the complete staging directory to the final run ID. A crash before publication therefore cannot reserve the final run ID; retry uses a new staging directory. `cleanup_abandoned_staging` removes only validated, old provider-owned staging directories and supports dry-run. The provider verifies transferred payload bytes before publication. Reusing a completed run ID fails and never replaces the existing artifact. Provider-controlled run directories and child files may not be symlinks or Windows junctions/reparse directories. Delete is restricted to a validated completed run below the provider root and first atomically renames it to a unique provider-owned quarantine name.

S3, Backblaze B2, Google Drive and OneDrive adapters should implement the same opaque-object operations. Cloud credentials, SDKs, retries and multipart uploads are intentionally not part of MRK-25. A future provider must preserve immutable create semantics and publish a completion boundary equivalent to the filesystem marker.

## Encryption

`Encryptor` is a small adapter with separate `can_encrypt` / `can_decrypt` capabilities plus `encrypt` and `decrypt`. Tests use a deterministic fake adapter; it is not production cryptography.

`AgeEncryptor` supports the external [age](https://age-encryption.org/) executable with recipient-based encryption. Install and key provisioning are deployment responsibilities. The recipient and identity-file path are runtime inputs; neither identity contents nor key/secret values enter metadata or structured status. Subprocess output and raw exceptions are not exposed.

When encryption is required:

- no adapter or unavailable executable => `encryption_failure`;
- missing decryption identity/capability => `encryption_failure` before publication;
- encryption failure => no completed offsite run;
- verification without a usable decryption identity => `encryption_failure`.

Before publication, the newly encrypted artifact is decrypted back into scratch and the complete DB/manifest/media checksum contract is verified again. Successful encryption alone is therefore never reported as a completed, restorable copy.

This workstation has OpenSSL 3.3, but not `age`, `7z`, GPG or the PostgreSQL CLI tools. OpenSSL is not selected automatically because MRK-25 does not define a safe passphrase/key lifecycle for it. No global dependency was installed.

## Safe metadata and outcomes

`metadata.json` has exactly these fields:

- `run_id`, `run_time` (UTC);
- `source_backup_identifier` (filename only);
- `encrypted`;
- `transfer_completed`;
- `checksum_result`;
- `offsite_target_identifier` (logical identifier, never an absolute path).

Structured outcomes are allowlisted: `success`, `local_backup_failure`, `encryption_failure`, `offsite_transfer_failure`, `verification_failure`, and `retention_cleanup_failure`. They contain operation, success, run ID and UTC start/finish times, but no raw exception, path, URL, credential or environment value.

## Retention

The pure `plan_retention` helper is provider-independent and useful for deterministic dry-runs. An executable cleanup plan must come from `plan_verified_retention`, which retrieves and fully verifies every candidate immediately before planning; `cleanup_retention` refuses a non-fresh plan. A corrupt newest artifact is marked invalid and cannot displace an older recoverable backup.

Retention defaults to the `Europe/Prague` calendar while storing/comparing aware UTC instants. It keeps the newest freshly verified completed run in each of:

- the 14 newest distinct local days;
- the 8 newest distinct local ISO weeks;
- the 12 newest distinct local months.

The three sets are unioned by run ID. The newest valid completed run is always retained, even if all tier counts are zero. Within every bucket only its newest run qualifies. Invalid/incomplete metadata is reported separately and is never automatically deleted.

`cleanup_retention(..., dry_run=True)` returns the deterministic delete set without calling the provider. Real cleanup requires `plan.verification_fresh`, records individual successes/failures and returns `retention_cleanup_failure` if any deletion fails; it does not hide partial cleanup.

## Scratch restore drill and TAR safety

`verify_offsite_run` downloads a copy to a temporary directory, decrypts there when required, validates every TAR member before extraction, then re-runs the existing DB/manifest/media checksum contract against the extracted copy.

Extraction rejects absolute paths, Windows drive paths, `..`, duplicate members, symlinks, hardlinks, devices, FIFOs and any resolved escape from scratch. Only regular files and directories are created. Verification never invokes production database tools and never writes to the production media directory.

The current local drill is integrity-only because `psql`, `createdb`, `dropdb` and `pg_restore` are not available. A later local acceptance step may restore a **copy** into a uniquely named disposable PostgreSQL database, validate it, and drop it in a `finally` path. That operation must require an explicitly test/scratch connection and must never infer the production database as a destination.

## MRK-23 and MRK-26 integration contract

MRK-25 does not add a scheduler, notifications or `/health`. Later integration should persist or expose only:

- last attempt and last success timestamps;
- the allowlisted outcome code;
- encrypted yes/no and safe target identifier;
- verification/cleanup success flags or counts.

MRK-26 may map these fields to its proposed off-machine monitoring observation. MRK-23 may expose the same allowlisted aggregate in `/health` after its runtime contract is resolved. Neither integration should include raw errors, filenames, filesystem paths or credentials, and neither should create a second copy implementation.

## Focused verification

From the repository root:

```sh
python -m pytest backend/tests/test_offsite_backup.py -q
python -m pytest backend/tests/test_backup.py backend/tests/test_monitoring.py -q
python -m pyflakes backend/offsite_backup.py backend/tests/test_offsite_backup.py
```

All automated MRK-25 tests use temporary directories. The existing local backup layout may be tested only read-only: select a successful run JSON, pass its `BACKUP_DIR` to `copy_completed_run`, and point `LocalFilesystemOffsiteTarget` at a temporary directory.
