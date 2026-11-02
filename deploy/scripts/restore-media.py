#!/usr/bin/env python3
"""Restore media from a verified Standa Hub backup manifest."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()

    root = args.backup_root.resolve(strict=True)
    manifest = args.manifest.resolve(strict=True)
    destination = args.destination.resolve()

    if not manifest.is_relative_to(root):
        parser.error("Manifest must be inside backup root")

    if args.destination.is_symlink() or destination.exists():
        parser.error("Destination already exists or is a symlink")

    if destination == root or root.is_relative_to(destination) or destination.is_relative_to(root):
        parser.error("Unsafe destination")

    protected = (
        Path("/"),
        Path("/srv/standa-hub-data/media"),
        Path("/srv/standa-hub-data/backups"),
    )

    if any(
        destination == path
        or path.is_relative_to(destination)
        or destination.is_relative_to(path)
        for path in protected
    ):
        parser.error("Destination overlaps a protected production path")

    run_manifest = args.run_manifest.resolve(strict=True)

    if not run_manifest.is_relative_to(root):
        parser.error("Run manifest must be inside backup root")

    run = json.loads(run_manifest.read_text())

    if run.get("status") != "success":
        parser.error("Backup run was not successful")

    expected_manifest = (
        root / run["media"]["manifest"]
    ).resolve(strict=True)

    if manifest != expected_manifest:
        parser.error("Media manifest does not match backup run")

    if sha256(manifest) != run["media"]["manifest_sha256"]:
        parser.error("Media manifest checksum mismatch")

    data = json.loads(manifest.read_text())
    files = data["files"]

    if len(files) != data["file_count"]:
        parser.error("Manifest file count mismatch")

    checked = []
    targets = set()
    total = 0

    for item in files:
        source = (root / item["archive_path"]).resolve(strict=True)
        target = (destination / item["relative_path"]).resolve()

        if not source.is_relative_to(root):
            parser.error("Source escapes backup root")

        if not target.is_relative_to(destination):
            parser.error("Target escapes destination")

        if target in targets:
            parser.error("Duplicate target")

        targets.add(target)

        if source.stat().st_size != item["size"]:
            parser.error("Source size mismatch")

        if sha256(source) != item["sha256"]:
            parser.error("Source checksum mismatch")

        checked.append((source, target, item))
        total += item["size"]

    if total != data["total_bytes"]:
        parser.error("Manifest total size mismatch")

    destination.mkdir(parents=True, mode=0o700)

    for source, target, item in checked:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

        if target.stat().st_size != item["size"]:
            raise RuntimeError("Restored file size mismatch")

        if sha256(target) != item["sha256"]:
            raise RuntimeError("Restored file checksum mismatch")

    print(f"RESTORED_MEDIA={len(checked)}")
    print(f"RESTORED_BYTES={total}")
    print("MEDIA_RESTORE_OK")


if __name__ == "__main__":
    main()
