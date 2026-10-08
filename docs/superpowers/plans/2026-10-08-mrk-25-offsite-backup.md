# MRK-25 Off-machine Backup Implementation Plan

> Execute in this dedicated worktree with strict red-green-refactor cycles. Do not touch MRK-19, Platform 2.0, production data, or real backup files.

## Task 1: Define source validation and safe result contracts

**Files:** `backend/offsite_backup.py`, `backend/tests/test_offsite_backup.py`

1. Write failing tests for successful schema-v1 source discovery and failures for non-success status, missing DB/manifest/media, checksum corruption, and escaping relative paths.
2. Run only the new focused test file and confirm expected failures.
3. Implement immutable descriptors, safe outcome enums/results, hashing, contained-path validation, and source-run loading with no source writes.
4. Re-run the focused tests to green and inspect for leaked raw exceptions or absolute paths.

## Task 2: Build deterministic self-contained TAR packages securely

**Files:** `backend/offsite_backup.py`, `backend/tests/test_offsite_backup.py`

1. Add failing tests proving the package contains exactly run JSON, DB dump, media manifest, and referenced media payloads while the source tree remains byte-for-byte unchanged.
2. Implement deterministic TAR creation in caller-owned temporary space with normalized relative member names.
3. Add failing malicious TAR tests for `../`, absolute paths, symlink escape, and hardlink escape.
4. Implement inspection-first safe extraction allowing only directories and regular files beneath scratch.
5. Re-run focused tests to green.

## Task 3: Add encryption abstraction and age adapter

**Files:** `backend/offsite_backup.py`, `backend/tests/test_offsite_backup.py`

1. Add failing fake-encryptor round-trip and required-encryption-unavailable tests, including a secret canary assertion over metadata and structured results.
2. Implement the encryptor protocol, explicit no-encryption path, fail-closed selection, and `AgeEncryptor` subprocess adapter using recipient/identity runtime inputs without logging or metadata persistence.
3. Add tests with mocked subprocess behavior for safe command construction and failure categorization; never invoke a real provider or install a tool.
4. Re-run focused tests to green.

## Task 4: Implement filesystem provider atomically

**Files:** `backend/offsite_backup.py`, `backend/tests/test_offsite_backup.py`

1. Add failing tests for store/list/retrieve/delete, existing-run non-overwrite, transfer failure, incomplete entry invisibility, path validation, and source immutability.
2. Implement the provider protocol and `LocalFilesystemOffsiteTarget` using root-contained run IDs, temporary staging, exclusive run reservation, and a completion marker written last.
3. Ensure failed publication cleans only its own incomplete reservation and never replaces existing content.
4. Re-run focused tests to green.

## Task 5: Implement deterministic retention policy

**Files:** `backend/offsite_backup.py`, `backend/tests/test_offsite_backup.py`

1. Add failing tests for newest-per-daily/weekly/monthly buckets, ISO-week and month/year boundaries, Prague local-midnight boundaries, tier deduplication, dry-run, invalid-run preservation, and unconditional newest valid preservation.
2. Implement a pure retention planner over aware UTC instants with explicit `ZoneInfo` conversion.
3. Add cleanup execution tests, including per-run provider deletion failure and structured partial-failure results.
4. Implement cleanup without deleting invalid/incomplete runs and re-run focused tests to green.

## Task 6: Add end-to-end offsite copy and scratch verification workflows

**Files:** `backend/offsite_backup.py`, `backend/tests/test_offsite_backup.py`

1. Add failing end-to-end tests for unencrypted and fake-encrypted copy/retrieve/verify flows.
2. Implement orchestration with explicit stage-to-safe-outcome mapping and metadata containing only approved fields.
3. Add/confirm failures for transfer, encryption, checksum corruption, missing DB/media, and secret canaries.
4. Run focused tests to green.

## Task 7: Document operations and integration contract

**Files:** `docs/offsite-backups.md`, `docs/backups.md`, `backend/AGENTS.md`

1. Document architecture, provider interface, filesystem provider, future cloud adapters, age requirements, retention, restore drill, and safe metadata.
2. Document MRK-23/MRK-26 structured-status integration points without wiring them.
3. Record local capability findings and the deferred real PostgreSQL scratch restore.

## Task 8: Verification, review, and delivery

1. Run focused MRK-25 tests, then the existing targeted backup and monitoring tests.
2. Run static checks used by the repository for changed backend files.
3. Run an integrity restore drill in temporary directories using a copied representation of the existing local backup format; never modify the original.
4. Review the final diff for secrets, absolute user paths, unsafe overwrite/delete, traversal, misleading success, and Platform 2.0/MRK-19 overlap.
5. Commit, push `codex/mrk-25-offsite-backup`, open and attach a PR, post Linear results, and move MRK-25 to In Review. Do not merge.
