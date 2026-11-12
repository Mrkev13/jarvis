#!/usr/bin/env python3
"""Verify an extracted release against the exact Git commit tree."""

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

# DEPLOY_RELEASES: isolated tests only (backend/tests/test_deploy_v3.py)
RELEASES = Path(os.environ.get("DEPLOY_RELEASES", "/srv/standa-hub/releases"))


def git(*args):
    return subprocess.check_output(
        ["git", *args],
        stderr=subprocess.PIPE,
    )


def fail(message):
    raise SystemExit(f"RELEASE_INVALID: {message}")


def main():
    if len(sys.argv) != 2:
        fail("Usage: verify-release.py COMMIT_SHA")

    commit = sys.argv[1]

    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        fail("Invalid commit SHA")

    actual_commit = git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    if actual_commit != commit:
        fail("Commit mismatch")

    release = RELEASES / commit

    if not release.is_dir() or release.is_symlink():
        fail("Release directory missing or symlinked")

    tree = git("ls-tree", "-rz", "--full-tree", commit).split(b"\0")
    expected = {}
    expected_dirs = set()

    for entry in tree:
        if not entry:
            continue

        metadata, raw_name = entry.split(b"\t", 1)
        mode, obj_type, oid = metadata.decode().split()

        if obj_type != "blob" or mode not in ("100644", "100755", "120000"):
            fail(f"Unsupported Git entry: {os.fsdecode(raw_name)}")

        name = os.fsdecode(raw_name)
        path = PurePosixPath(name)

        if path.is_absolute() or ".." in path.parts:
            fail(f"Unsafe path: {name}")

        expected[name] = (mode, oid)

        for parent in list(path.parents)[:-1]:
            if str(parent) != ".":
                expected_dirs.add(str(parent))

    actual_files = set()
    actual_dirs = set()

    for root, dirs, files in os.walk(release, followlinks=False):
        base = Path(root)

        for name in dirs[:]:
            path = base / name
            relative = path.relative_to(release).as_posix()

            if path.is_symlink():
                actual_files.add(relative)
                dirs.remove(name)
            elif path.is_dir():
                actual_dirs.add(relative)
            else:
                fail(f"Unexpected directory entry: {relative}")

        for name in files:
            path = base / name
            relative = path.relative_to(release).as_posix()
            actual_files.add(relative)

    missing = set(expected) - actual_files
    extra = actual_files - set(expected)

    if missing:
        fail(f"Missing files: {sorted(missing)[:10]}")

    if extra:
        fail(f"Extra files: {sorted(extra)[:10]}")

    if actual_dirs != expected_dirs:
        fail(
            f"Directory mismatch: missing="
            f"{sorted(expected_dirs - actual_dirs)[:10]}, "
            f"extra={sorted(actual_dirs - expected_dirs)[:10]}"
        )

    for name, (mode, oid) in expected.items():
        path = release / name
        info = path.lstat()

        if mode == "120000":
            if not stat.S_ISLNK(info.st_mode):
                fail(f"Expected symlink: {name}")
            data = os.fsencode(os.readlink(path))
        else:
            if not stat.S_ISREG(info.st_mode):
                fail(f"Expected regular file: {name}")

            executable = bool(info.st_mode & 0o111)
            if executable != (mode == "100755"):
                fail(f"Executable permission mismatch: {name}")

            data = path.read_bytes()

        header = f"blob {len(data)}\0".encode()
        actual_oid = hashlib.sha1(header + data).hexdigest()

        if actual_oid != oid:
            fail(f"Content mismatch: {name}")

    print("RELEASE_CONTENT_VERIFIED")
    print(f"COMMIT={commit}")
    print(f"FILES={len(expected)}")


if __name__ == "__main__":
    main()
