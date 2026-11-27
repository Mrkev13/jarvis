#!/usr/bin/env python3
"""MRK-113: řízená propagace main -> produkční větev (release PR). Spouští ho .github/workflows/release-to-production.yml.

Kroky (fail closed, nikdy nic nemerguje):
1. zdrojový commit = zadané SHA nebo aktuální origin/main; musí být na main;
2. už je v produkční větvi -> nic (exit 0);
3. CI: nejnovější push run `ci.yml` přesně pro to SHA na main musí být completed/success, jinak exit 1 a žádný PR;
4. obsah: commity a PR (first-parent) mezi produkční větví a zdrojem;
5. Alembic head v produkční větvi vs. ve zdroji -> release s migrací dostane štítky a upozornění: automatický updater ho
   nenasadí (porovnává heady v image, ne stav DB) a vyžaduje řízený migrační deployment (MRK-114);
6. zkušební merge (`git merge-tree`) -> případné konflikty do popisu;
7. větev release/main-<sha12> připnutá na PŘESNÝ zdrojový commit (nikdy se nepřesouvá) a PR do produkční větve;
   už otevřený PR pro tu větev se jen aktualizuje;
8. MRK-150: starší otevřené release PR (jejich commit je předkem nového zdroje) se zavřou s odkazem na nový – nový
   release je obsahuje. Novější release se nikdy nezavře (ruční spuštění pro starší SHA nic nepřepíše). Nic se nemerguje.

Git čte z lokálního klonu (workflow dělá checkout s celou historií), GitHub API přes `gh api` (GH_TOKEN).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("REPO", "Mrkev13/jarvis")
SOURCE = "main"
PRODUCTION = "mrk-101-ubuntu-production"
VERSIONS = "backend/alembic/versions"
LABEL_RELEASE = "release"
LABEL_MIGRATION = "migration"
LABEL_MANUAL = "manual-merge"


class ReleaseError(RuntimeError):
    pass


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def gh(method: str, path: str, payload: dict | None = None) -> object:
    cmd = ["gh", "api", "-X", method, path]
    if payload is not None:
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None, capture_output=True, text=True)
    if r.returncode != 0:
        raise ReleaseError(f"gh api {method} {path}: {r.stderr.strip() or r.stdout.strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def is_ancestor(a: str, b: str) -> bool:
    return git("merge-base", "--is-ancestor", a, b, check=False).returncode == 0


# ---------- Alembic heads straight from the migration files of a ref (no import, no DB) ----------

_REV = re.compile(r"^revision\s*(?::\s*\w+\s*)?=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", re.M)


def alembic_heads(ref: str) -> list[str]:
    files = [f for f in git("ls-tree", "--name-only", f"{ref}:{VERSIONS}", check=False).stdout.split() if f.endswith(".py")]
    revisions, downs = set(), set()
    for name in files:
        text = git("show", f"{ref}:{VERSIONS}/{name}").stdout
        rev = _REV.search(text)
        if not rev:
            continue
        revisions.add(rev.group(1))
        down = _DOWN.search(text)
        if down:
            downs.update(re.findall(r"['\"]([^'\"]+)['\"]", down.group(1)))
    return sorted(revisions - downs)


# ---------- GitHub ----------

def ci_status(sha: str) -> str:
    """Nejnovější push run ci.yml pro přesné SHA na main: 'completed success' = schváleno."""
    data = gh("GET", f"repos/{REPO}/actions/workflows/ci.yml/runs?head_sha={sha}&branch={SOURCE}&event=push&per_page=20")
    runs = [r for r in (data or {}).get("workflow_runs", [])
            if r.get("head_sha") == sha and r.get("head_branch") == SOURCE and r.get("event") == "push"
            and str(r.get("path", "")).split("@")[0] == ".github/workflows/ci.yml"]
    if not runs:
        return "not found"
    run = max(runs, key=lambda r: (r["created_at"], r["id"]))
    return f"{run['status']} {run['conclusion']}"


def ensure_labels(names: list[str]) -> None:
    colors = {LABEL_RELEASE: "0e8a16", LABEL_MIGRATION: "d93f0b", LABEL_MANUAL: "b60205"}
    for name in names:
        try:
            gh("POST", f"repos/{REPO}/labels", {"name": name, "color": colors.get(name, "ededed")})
        except ReleaseError as e:  # 422 = už existuje
            if "already_exists" not in str(e) and "422" not in str(e):
                raise


# ---------- release ----------

def build_body(sha: str, commits: list[tuple[str, str]], prs: list[str], old_heads: list[str], new_heads: list[str],
               conflicts: list[str]) -> str:
    migration = old_heads != new_heads
    lines = [
        f"Release `main@{sha[:12]}` → `{PRODUCTION}`.",
        "",
        f"- **Zdrojový commit:** `{sha}` (větev `release/main-{sha[:12]}` je na něm pevně připnutá)",
        "- **CI zdroje:** push run `ci.yml` na `main` je `completed success`",
        f"- **Alembic head:** produkce `{', '.join(old_heads) or '—'}` → release `{', '.join(new_heads) or '—'}`",
        "",
    ]
    if migration:
        lines += [
            "> [!WARNING]",
            "> **Release mění Alembic head – vyžaduje řízený migrační deployment (MRK-114).**",
            "> Automatický updater tento commit nenasadí (porovnává heady v image, ne stav databáze), a to ani když",
            "> je databáze migrovaná předem. Mergovat až s naplánovaným řízeným nasazením migrace.",
            "",
        ]
    else:
        lines += ["Bez změny schématu: po merge a zeleném push CI na produkční větvi ho nasadí automatický updater.", ""]
    if conflicts:
        lines += ["> [!CAUTION]", "> Zkušební merge do produkční větve má konflikty: "
                  + ", ".join(f"`{c}`" for c in conflicts[:20]) + ". Vyřeš je v release větvi (merge produkce do ní).", ""]
    lines += [f"## Zahrnuté změny ({len(commits)} commitů, first-parent)", ""]
    lines += [f"- `{h[:7]}` {s}" for h, s in commits[:100]]
    if len(commits) > 100:
        lines.append(f"- … a dalších {len(commits) - 100}")
    if prs:
        lines += ["", "PR: " + ", ".join(f"#{n}" for n in prs)]
    lines += ["", "Workflow `Release to production` nic nemerguje; merge dělá Standa ručně (AGENTS.md).", ""]
    return "\n".join(lines)


def run(sha_input: str, dry_run: bool) -> int:
    git("rev-parse", "--verify", f"origin/{SOURCE}^{{commit}}")
    git("rev-parse", "--verify", f"origin/{PRODUCTION}^{{commit}}")
    sha = git("rev-parse", "--verify", f"{sha_input or 'origin/' + SOURCE}^{{commit}}").stdout.strip()
    if not is_ancestor(sha, f"origin/{SOURCE}"):
        raise ReleaseError(f"SOURCE_NOT_ON_MAIN: {sha}")
    print(f"SOURCE_COMMIT={sha}")
    if is_ancestor(sha, f"origin/{PRODUCTION}"):
        print("ALREADY_IN_PRODUCTION")
        return 0

    status = ci_status(sha)
    if status != "completed success":
        print(f"CI_NOT_APPROVED: {status}")
        return 1
    print("CI_APPROVED")

    log = git("log", "--first-parent", "--format=%H%x09%s", f"origin/{PRODUCTION}..{sha}").stdout.splitlines()
    commits = [tuple(line.split("\t", 1)) for line in log if "\t" in line]
    prs = sorted({m.group(1) for _, s in commits for m in [re.match(r"Merge pull request #(\d+)", s)] if m}, key=int)
    old_heads, new_heads = alembic_heads(f"origin/{PRODUCTION}"), alembic_heads(sha)
    migration = old_heads != new_heads
    print(f"ALEMBIC_HEADS: {','.join(old_heads) or '-'} -> {','.join(new_heads) or '-'}")
    print("MIGRATION_RELEASE" if migration else "NO_MIGRATION")

    merge = git("merge-tree", "--write-tree", "--name-only", f"origin/{PRODUCTION}", sha, check=False)
    conflicts = []
    if merge.returncode == 1:
        out = merge.stdout.split("\n\n", 1)[0].splitlines()[1:]
        conflicts = sorted({c for c in out if c})
        print(f"MERGE_CONFLICTS: {len(conflicts)}")
    elif merge.returncode != 0:
        raise ReleaseError(f"git merge-tree: {merge.stderr.strip()}")

    body = build_body(sha, commits, prs, old_heads, new_heads, conflicts)
    branch = f"release/main-{sha[:12]}"
    title = f"Release: main@{sha[:12]} → produkce" + (" (MIGRACE)" if migration else "")
    labels = [LABEL_RELEASE] + ([LABEL_MIGRATION, LABEL_MANUAL] if migration else [])
    if dry_run:
        print(f"DRY_RUN: {title}\n{body}")
        return 0

    remote = git("ls-remote", "origin", f"refs/heads/{branch}").stdout.split()
    if remote and remote[0] != sha:
        raise ReleaseError(f"RELEASE_BRANCH_MOVED: {branch} != {sha}")
    if not remote:
        git("push", "origin", f"{sha}:refs/heads/{branch}")
    owner = REPO.split("/")[0]
    existing = gh("GET", f"repos/{REPO}/pulls?state=open&head={owner}:{branch}&base={PRODUCTION}") or []
    if existing:
        number = existing[0]["number"]
        gh("PATCH", f"repos/{REPO}/pulls/{number}", {"title": title, "body": body})
        print(f"RELEASE_PR_UPDATED: #{number}")
    else:
        number = gh("POST", f"repos/{REPO}/pulls", {"title": title, "head": branch, "base": PRODUCTION, "body": body,
                                                    "maintainer_can_modify": False})["number"]
        print(f"RELEASE_PR_CREATED: #{number}")
    ensure_labels(labels)
    gh("POST", f"repos/{REPO}/issues/{number}/labels", {"labels": labels})
    supersede_older(sha, number)
    return 0


def supersede_older(sha: str, number: int) -> None:
    """MRK-150: zavře otevřené release PR, jejichž commit nový release obsahuje (jen release/main-*, ne ruční PR)."""
    open_prs = gh("GET", f"repos/{REPO}/pulls?state=open&base={PRODUCTION}&per_page=100") or []
    for pr in open_prs:
        head = pr.get("head") or {}
        old_sha = str(head.get("sha") or "")
        if (pr.get("number") == number or not str(head.get("ref") or "").startswith("release/main-")
                or not re.fullmatch(r"[0-9a-f]{40}", old_sha) or old_sha == sha or not is_ancestor(old_sha, sha)):
            continue
        gh("POST", f"repos/{REPO}/issues/{pr['number']}/comments",
           {"body": f"Nahrazeno novějším release PR #{number} (main@{sha[:12]}), který tyto změny obsahuje."})
        gh("PATCH", f"repos/{REPO}/pulls/{pr['number']}", {"state": "closed"})
        print(f"RELEASE_PR_SUPERSEDED: #{pr['number']}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sha", default="", help="commit z main (prázdné = aktuální origin/main)")
    p.add_argument("--dry-run", action="store_true", help="jen vypsat, nic nepushovat ani nezakládat")
    a = p.parse_args()
    if a.sha and not re.fullmatch(r"[0-9a-f]{7,40}", a.sha):
        print("INVALID_SHA", file=sys.stderr)
        return 2
    try:
        return run(a.sha, a.dry_run)
    except ReleaseError as e:
        print(f"RELEASE_FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
