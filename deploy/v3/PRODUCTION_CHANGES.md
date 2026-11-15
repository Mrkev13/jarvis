# MRK-108 v3 – production changes after the import

`SHA256SUMS.original` stays the proof of the state at the first import (commit 4f5049e). Changes made directly on
the production server afterwards are recorded here, newest last, with the SHA-256 of the installed file.

## 2026-11-12 – CI check from the root-owned copy

Changed on the Ubuntu server:

- `/usr/local/lib/standa-hub/auto-update-v3.sh`
- `/usr/local/lib/standa-hub/deploy-transaction-v3.sh`

In both scripts, the CI check path changed from `$ROOT/deploy/scripts/check-ci.sh` (the dev checkout) to
`/usr/local/lib/standa-hub/mrk108/check-ci.sh` (root:root, 755, SHA-256
`4d9e271e86aefbaf6f6c91cc1ab02d51c81345037a78555c6ecd31ba01b42334` = `deploy/scripts/check-ci.sh` at 932e2fc).
The call stays `runuser -u standa -- "/usr/local/lib/standa-hub/mrk108/check-ci.sh" "$TARGET"`.

| Installed file | SHA-256 after the change |
| --- | --- |
| `auto-update-v3.sh` | `53afd9fd74946df401eade57f3d7a53c04239eb44075059f1d92a3b48c579dfc` |
| `deploy-transaction-v3.sh` | `c3f1de5020ce7711e230d3d8851d9893291f7c1e6d58a3d7752eec06d6f36019` |

The sums identify the installed files; they cannot be recomputed from this repository because the copies here are
redacted (`<tailnet-host>`) and carry the PR #65 review changes. The scope of the edit (only the CI path) was checked
on the server when it was made.

Verified on the server: the CI check for production commit `32db7b8` → `CI_APPROVED`, exit 0; the systemd updater run
afterwards → `Result=success`, `ExecMainStatus=0`, `NO_UPDATE_NEEDED`.

Not deployed: the PR #65 review version (da866d5 and later). Automatic `--apply` stays off.
