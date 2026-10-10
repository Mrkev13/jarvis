"""MRK-56: thin folder wrapper over the shared Moodle course-ZIP import core.

Imports every `*.zip` directly in FOLDER (not recursive) with exactly the same validation, identity and transaction
rules as the UI upload (`modules.school.zip_import.import_course_export`). It is a one-shot CLI – no server, no
scheduler. Prints only file names and counts.

    cd backend
    python scripts/import_moodle_zips.py C:\\Studium\\Moodle --env-file C:\\StandaHub\\backend\\.env.production
"""
import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('folder', type=Path)
    parser.add_argument('--env-file', type=Path, help='protected production env file (else the normal environment)')
    args = parser.parse_args(argv)
    if args.env_file:
        from production import load_production_environment
        load_production_environment(str(args.env_file))
    import database
    from modules.school import zip_import

    if not args.folder.is_dir():
        print('Složka neexistuje.')
        return 2
    archives = sorted(p for p in args.folder.glob('*.zip') if p.is_file())
    if not archives:
        print('Ve složce nejsou žádné ZIP soubory.')
        return 0
    failures = 0
    for path in archives:
        if path.stat().st_size > zip_import.max_archive_bytes():
            print(f'{path.name}: přeskočeno (archive_too_large)')
            failures += 1
            continue
        db = database.SessionLocal()
        try:
            with path.open('rb') as handle:
                stats = zip_import.import_course_export(db, handle)
            print(f"{path.name}: nové {stats['created']}, změněné {stats['updated']}, beze změny {stats['unchanged']}, "
                  f"uložené soubory {stats['file_stored']}, nepodporované {stats['file_unsupported']}, "
                  f"chybí v ZIPu {stats['files_listed_missing']}")
        except zip_import.ZipImportError as error:
            print(f'{path.name}: chyba ({error.category})')
            failures += 1
        finally:
            db.close()
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
