# Off-machine backup copies (MRK-25, MRK-57)

## Production: restic → Backblaze B2 (MRK-57)

**Architecture**

- The local pipeline (`backup_service.run_backup`, [backups.md](backups.md)) stays the only source of truth.
- After the daily local backup, the hourly scheduler job runs `offsite_restic.run_scheduled`. That step:
  1. picks the newest **successful** `BackupLog`;
  2. re-verifies its run with the MRK-25 contract (`offsite_backup._load_source_run`: run JSON, dump SHA-256,
     manifest and every media archive file);
  3. uploads exactly those files with `restic backup` into one repository on Backblaze B2.
- The upload never reads the live DB or `MEDIA_DIR`.
- **Local backup success never depends on the network.** The off-site step is a separate `try` after the local step,
  and a B2 outage only shows up in `/health.offsite` and an alert.
- **restic** provides client-side encryption (AES-256 + Poly1305 under a repository password), content-defined
  deduplication (only new chunks are uploaded), snapshots, retention and integrity checks. Each upload is one snapshot
  tagged `standa-hub` + `run:<local run id>`, with the fixed host `standa-hub`.
- **B2 is accessed through its S3-compatible API**, which restic recommends over the native `b2:` backend.

### Behaviour

| When | What | Notes |
|---|---|---|
| Every hourly cycle | Upload the newest verified local run if it has no successful off-site record | Only a clean exit tags the snapshot `complete`; a partial snapshot (exit 3, e.g. a locked file) never counts. Idempotent: an existing `run:<id>` + `complete` snapshot (e.g. after a crash) is reused, never duplicated. A failed or missed upload retries next hour. `restic unlock` first removes only *stale* locks. |
| ~daily (≥ 20 h since the last check **attempt**) | `restic check` (metadata only) | No data download. Cadence follows attempts, so a failing check or prune backs off to daily/weekly instead of repeating hourly. |
| Weekly (≥ 7 days since the last prune attempt) | `restic check --read-data-subset 5%`, then **only if it passed** `restic forget --tag standa-hub --group-by host --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune` | `--group-by host`: snapshot paths differ per run, so grouping by paths would never forget anything. A failed prune leaves existing snapshots intact. |

**Concurrency and time bound:**
- one deadline (`OFFSITE_TIMEOUT_SECONDS`, default 3600) bounds the whole cycle, every restic call included, so an unreachable B2 can never hold the hourly job (and the next local backup) for hours;
- one off-site operation per backend process (lock), and restic's own repository lock;
- the scheduler has a single owner (MRK-23);
- a `running` record older than twice the timeout is marked `interrupted` and retried.

**History** goes into `offsite_backup_runs` (migration `0024`). It holds only the operation, status, an allowlisted
outcome code, the local backup id/run id, the snapshot id, new files/bytes and timestamps: never credentials, the
repository URL, paths or raw restic output.

**Outcome codes:** `success`, `already_uploaded`, `no_source`, `busy`, `not_configured`, `misconfigured`,
`source_invalid`, `auth_failed`, `network_unavailable`, `repository_missing`, `wrong_password`, `locked`, `timeout`,
`interrupted`, `source_incomplete`, `check_failed`, `restic_failed`.

### Health and alerts

`/health.offsite` contains:
- `configured`, `status` (`disabled | fresh | stale | check_failed | misconfigured | unknown`), `degraded`;
- `last_attempt_at` / `last_attempt_outcome`, `last_success_at`, `source_backup_id`, `age_seconds`, `max_age_seconds`
  (26 h);
- last check and prune time and status, the retention policy, `encrypted: true`.

No bucket, endpoint, account, key, password, path or raw output ever appears there. Once configured, **no successful
off-site copy for more than 26 h, a failed repository check, or an unusable configuration** turns the overall status
`degraded` (HTTP 200). Before the first upload the status is `stale`, which is honest.

Every failure upserts one bell notification per operation (`offsite:backup|check|prune`, type `ops_alert`, fixed
Czech text plus the outcome code); the next success resolves it. `ops_alert` is a Web Push deliverable type
(`OPS_ALERT_PUSH`, default on), so when MRK-24 HTTPS push is live the same alert reaches the phone through the
existing delivery queue. The MRK-26 monitoring log records only `off_machine` + `ok/warning`.

### Backblaze B2 setup (owner, once; never paste these values anywhere)

1. **Bucket:**
   - Private, with a globally unique name.
   - Note its **S3 endpoint** (bucket details, e.g. `s3.<region>.backblazeb2.com`).
   - **Lifecycle:** *Keep prior versions for this number of days* = **30**. With the S3 API, restic deletes by
     *hiding* objects, so this keeps every pruned or hidden object recoverable for 30 days, including after a
     malicious "delete everything" with the upload key.
   - **Object Lock: off.** restic over the S3 API with Object Lock is not verified here.
   - Server-side encryption is optional, since restic already encrypts client-side.
2. **Upload application key** restricted to that bucket:
   - Capabilities `listBuckets`, `listAllBucketNames` (needed by bucket-restricted keys), `listFiles`, `readFiles`,
     `writeFiles`.
   - **Hardened variant: without `deleteFiles`.** Backblaze documents `writeFiles` for deleting by name (a hide) and
     `deleteFiles` for deleting a specific version. Whether S3 DeleteObject-by-name works without `deleteFiles` is
     **verified during production acceptance**: `restic backup`, `unlock` and `forget --prune` must all succeed. If
     it fails, use the web console's read-and-write key, which includes deletion, and rely on the 30-day lifecycle
     window.
   - The web console's key types may not let you leave out `deleteFiles`. The B2 CLI can create a key with an exact
     capability list (`b2 key create …`; check `--help` for the current syntax).
   - Copy the **keyID** and **applicationKey** (shown once) only into the local protected file (step 4).
3. **Separate maintenance credential: not needed by default.** Because prune only *hides* objects, the automated key
   can't destroy history. Real deletion happens only through the bucket lifecycle rule or your own account login,
   which never lives on this machine. If you want prune on a different key anyway, set
   `OFFSITE_MAINTENANCE_SECRETS_FILE` to a second protected file in the same format; only the weekly prune uses it.
4. **Secrets on the production machine**, in an elevated PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows\offsite-secrets.ps1 -Mode Prepare -GeneratePassword
   notepad C:\ProgramData\StandaHub\offsite\b2.env          # fill RESTIC_REPOSITORY / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
   notepad C:\ProgramData\StandaHub\offsite\restic-password.txt   # copy the generated password into your password manager
   powershell -ExecutionPolicy Bypass -File scripts\windows\offsite-secrets.ps1 -Mode Check   # names/booleans only
   ```

   - `RESTIC_REPOSITORY=s3:https://<s3 endpoint>/<bucket>/standa-hub`.
   - The folder and files are **SYSTEM + Administrators only** (inheritance off) and live outside the git checkout.
     The restic password is a separate file from the B2 key.
   - **Repository password warning:** without it, the off-site copy can never be decrypted, and Backblaze can't help.
     Keep it, plus the keyID/applicationKey or your B2 login, **off this machine**. Losing the PC must not lose them.
5. **`backend\.env.production`** (protected, edit in place):

   ```
   OFFSITE_BACKUP_ENABLED=true
   OFFSITE_RESTIC_PATH=C:\Program Files\WinGet\Packages\restic.restic_Microsoft.Winget.Source_8wekyb3d8bbwe\restic_<version>_windows_amd64.exe
   OFFSITE_SECRETS_FILE=C:\ProgramData\StandaHub\offsite\b2.env
   OFFSITE_RESTIC_PASSWORD_FILE=C:\ProgramData\StandaHub\offsite\restic-password.txt
   # optional: OFFSITE_TIMEOUT_SECONDS=3600, OFFSITE_MAINTENANCE_SECRETS_FILE=…, OPS_ALERT_PUSH=true
   ```

   `production.py` refuses an off-site setup that isn't absolute and separate, or that has no local backup
   (`BACKUP_ENABLED`). restic is installed machine-wide (`winget install --id restic.restic --source winget --scope
   machine`) under `C:\Program Files\WinGet\Packages`, where only SYSTEM/Administrators can write and SYSTEM can
   execute. Use the absolute path, because the task runs as SYSTEM.
6. **Create the repository once:** `python -m offsite_restic --env-file <env> init` (it refuses an existing
   repository). Then restart `StandaHub-Backend`.

### Operator CLI (elevated, in `C:\StandaHub\backend`)

`python -m offsite_restic --env-file <protected env>` followed by one of:
- `status`: the same JSON as `/health.offsite`;
- `backup`: upload the newest verified run now;
- `check [--read-data]`;
- `prune`: sampled check first;
- `snapshots`: count and newest time only;
- `restore --target <empty scratch dir> [--snapshot <id>|latest]`.

The CLI prints outcome codes only.

### Restore from B2 (drill or disaster)

1. On any machine with restic, the two protected files and network access:
   `python -m offsite_restic --env-file <env> restore --target D:\restore-drill`. Or plain restic:
   `restic -r s3:https://… restore latest --target <dir>` with the same environment variables and password file.
2. The CLI refuses targets inside `BACKUP_DIR`/`MEDIA_DIR` and non-empty targets. After restoring, it re-runs the
   MRK-25 checksum contract on the restored run (run JSON, dump, manifest, every media file).
3. The restored tree has exactly the local `BACKUP_DIR` layout (`runs/`, `standa_hub_<ts>.pgdump.gz`,
   `media/manifests`, `media/archive`). Continue with [backups.md → Obnova](backups.md#obnova): scratch DB, scratch
   media, verify, and only then switch over. `latest` means the newest snapshot tagged `complete`.
4. **Mini PC / Linux (MRK-27, MRK-49):** the same repository URL, keys and password work with restic on Linux. The
   new host keeps `--host standa-hub` (that is the code's constant), so the snapshot history and retention continue
   in one lineage. Run a restore drill there first, never an experiment on the only original.

## MRK-25 integrity library

The rest of this document describes the MRK-25 library. Its run and manifest verification is the gate before every
restic upload and after every restore. The TAR + `age` + filesystem-target path below remains a tested,
provider-independent fallback, but **production uses restic → B2** (above).

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

When MRK-25 was built, the workstation had OpenSSL 3.3, but not `age`, `7z`, GPG or the PostgreSQL CLI tools (the production Windows machine now has the PostgreSQL 18 client tools). OpenSSL is not selected automatically because MRK-25 does not define a safe passphrase/key lifecycle for it. No global dependency was installed.

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

The pure `plan_retention` helper is provider-independent and useful for deterministic previews. `cleanup_retention` is dry-run only and refuses destructive execution. Real deletion is exposed only through `apply_verified_retention`, which retrieves and fully verifies every candidate, creates the plan, revalidates every retained run, and then executes deletion inside the same operation. A stale/caller-constructed plan therefore cannot authorize deletion, and a corrupt newest artifact cannot displace an older recoverable backup.

Retention defaults to the `Europe/Prague` calendar while storing/comparing aware UTC instants. It keeps the newest freshly verified completed run in each of:

- the 14 newest distinct local days;
- the 8 newest distinct local ISO weeks;
- the 12 newest distinct local months.

The three sets are unioned by run ID. The newest valid completed run is always retained, even if all tier counts are zero. Within every bucket only its newest run qualifies. Invalid/incomplete metadata is reported separately and is never automatically deleted.

`cleanup_retention(..., dry_run=True)` returns the deterministic delete set without calling the provider. `apply_verified_retention` aborts without deleting anything when retained-run revalidation fails; otherwise it records individual deletion successes/failures and returns `retention_cleanup_failure` if any deletion fails. It does not hide partial cleanup.

## Scratch restore drill and TAR safety

`verify_offsite_run` downloads a copy to a temporary directory, decrypts there when required, validates every TAR member before extraction, then re-runs the existing DB/manifest/media checksum contract against the extracted copy.

Extraction rejects absolute paths, Windows drive paths, `..`, duplicate members, symlinks, hardlinks, devices, FIFOs and any resolved escape from scratch. Only regular files and directories are created. Verification never invokes production database tools and never writes to the production media directory.

`verify_offsite_run` itself stays integrity-only. A full local database drill (restore of a local run into a disposable `standa_hub_restore_drill` database plus scratch media, application read checks, then cleanup) was performed on the production machine on 2026-10-11; procedure and result are in [backups.md](backups.md#obnova). A restore from an actual off-machine copy has not been performed yet. Any such step must restore a **copy** into a uniquely named disposable PostgreSQL database, validate it, and drop it in a `finally` path. That operation must require an explicitly test/scratch connection and must never infer the production database as a destination.

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
