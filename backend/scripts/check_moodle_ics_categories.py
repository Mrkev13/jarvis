"""MRK-76: does the real Moodle ICS export carry the course in CATEGORIES? Read-only check, nothing is stored.

Downloads the configured feed (`MOODLE_ICS_URL`, same rules as the sync) and prints ONLY counts and value shapes
(letters → A, digits → 9) – never the URL, titles, course names or descriptions. With the database reachable it also
counts how many category values match a mapped study course. Paste the output into the issue as is.

    cd backend
    python scripts/check_moodle_ics_categories.py --env-file C:\\StandaHub\\backend\\.env.production
"""
import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# words Moodle uses for quiz/assignment open–close pairs (CZ + EN); only counted, never printed
OPEN_CLOSE = re.compile(r'(otev[řr]|uzav[řr]|zav[ří]r|opens?\b|closes?\b|\bdue\b|odevzd)', re.IGNORECASE)


def shape(value: str) -> str:
    return re.sub(r'[^\W\d_]', 'A', re.sub(r'\d', '9', value))


def report(data: bytes, course_keys=None) -> list[str]:
    from icalendar import Calendar
    from modules.calendar.parser import _course_ref

    events = Calendar.from_ical(data).walk('VEVENT')
    with_prop = sum(1 for e in events if e.get('CATEGORIES') is not None)
    refs = [_course_ref(e) for e in events]
    usable = [r for r in refs if r]
    distinct = {r.strip().casefold() for r in usable}  # matching ignores case and outer spaces
    lines = [f'Událostí: {len(events)}',
             f'S CATEGORIES: {with_prop} ({"ano" if with_prop else "ne"})',
             f'S jednoznačnou hodnotou (použitelné pro párování): {len(usable)}',
             f'Různých hodnot (bez ohledu na velikost písmen): {len(distinct)}']
    for value, count in Counter(shape(r) for r in usable).most_common(5):
        lines.append(f'  tvar {value!r} (délka {len(value)}): {count}×')
    lines.append(f'Názvy typu otevírá/uzavírá/odevzdání: '
                 f'{sum(1 for e in events if OPEN_CLOSE.search(str(e.get("SUMMARY") or "")))}')
    if course_keys is not None:
        lines.append(f'Hodnot, které odpovídají namapovanému kurzu: {len(distinct & set(course_keys))} z {len(distinct)}')
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--env-file', type=Path, help='protected production env file (else the normal environment)')
    parser.add_argument('--no-db', action='store_true', help='skip the match against mapped study courses')
    args = parser.parse_args(argv)
    if args.env_file:
        from production import load_production_environment
        load_production_environment(str(args.env_file))
    from modules.calendar import service

    url = service.feed_url()
    if not url:
        print('MOODLE_ICS_URL není nastavená.')
        return 2
    try:
        data = service.fetch_feed(url)
    except service.CalendarSyncError as error:
        print(f'Stažení selhalo: {error.category}')  # allowlisted category only, never the URL
        return 1
    course_keys = None
    if not args.no_db:
        try:
            import database
            from school_moodle import course_subjects
            db = database.SessionLocal()
            try:
                course_keys = set(course_subjects(db))
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - the feed check works without the database
            print('Databáze nedostupná – párování s kurzy přeskočeno.')
    for line in report(data, course_keys):
        print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
