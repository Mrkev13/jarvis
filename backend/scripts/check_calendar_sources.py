"""MRK-103: why does a calendar source (Google, Moodle) not sync? Read-only check, nothing is stored.

For every allowlisted source (modules/calendar/service.SOURCES) it prints ONLY status lines: which env variable is
set, whether the value has outer quotes/whitespace, https, expected host, DNS, download result (the same
allowlisted category as the sync) and the number of events. Never the URL, host, token, titles or ICS content.
Paste the output into the issue as is.

In the production container (the same environment as the running backend):

    docker exec standa-hub-backend python scripts/check_calendar_sources.py

With an env file instead of the process environment:

    cd backend && python scripts/check_calendar_sources.py --env-file <protected production env>
"""
import argparse
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Expected host per source where it is known (Google's secret iCal address); compared, never printed.
EXPECTED_HOSTS = {'google': 'calendar.google.com'}


def _yes(value: bool) -> str:
    return 'ano' if value else 'ne'


def check_source(key, environ=None, *, fetch=None, resolve=None) -> tuple[bool, list[str]]:
    """(ok, lines) for one source. `environ`, `fetch` and `resolve` are injectable for tests."""
    from modules.calendar import service
    from modules.calendar.parser import parse_ics

    environ = os.environ if environ is None else environ
    name, env_names = service.SOURCES[key]
    lines = [f'[{key}] {name}']
    set_name = next((n for n in env_names if (environ.get(n) or '').strip()), None)
    if set_name is None:
        lines.append(f'  proměnná: žádná z {", ".join(env_names)} není nastavená → feed_not_configured')
        return False, lines
    raw = environ[set_name]
    stripped = raw.strip()
    quoted = len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in '"\''
    url = service._unquote(stripped)
    lines.append(f'  proměnná: {set_name} (nastavená)')
    lines.append(f'  mezery kolem hodnoty: {_yes(raw != stripped)}; uvozovky kolem hodnoty: {_yes(quoted)}'
                 + (' (od MRK-103 se odstraní)' if quoted else ''))
    try:  # urlsplit/hostname raise ValueError quoting part of the address (Codex review #74) – never let it out
        parts = urlsplit(url)
        host = parts.hostname
        https = parts.scheme == 'https' and bool(host)
        invalid = not https or bool(parts.username or parts.password or parts.fragment)
    except Exception:  # noqa: BLE001
        lines.append('  výsledek: invalid_feed_configuration (adresu nelze přečíst)')
        return False, lines
    lines.append(f'  https a host: {_yes(https)}; mezery uvnitř: {_yes(any(c.isspace() for c in url))}')
    if invalid:
        lines.append('  výsledek: invalid_feed_configuration (adresa musí být https bez jména, hesla a #)')
        return False, lines
    expected = EXPECTED_HOSTS.get(key)
    if expected:
        lines.append(f'  host odpovídá {expected}: {_yes(host.lower() == expected)}')
    try:
        (resolve or socket.getaddrinfo)(host, 443)
        lines.append('  DNS: ok')
    except Exception:  # noqa: BLE001 - only the category is reported
        lines.append('  DNS: selhalo (kontejner nepřeloží host – DNS / síť)')
        return False, lines
    try:
        data = (fetch or service.fetch_feed)(url)
    except service.CalendarSyncError as error:
        lines.append(f'  stažení: {error.category}')
        return False, lines
    except Exception:  # noqa: BLE001 - never print the exception (it may contain the URL)
        lines.append('  stažení: feed_unavailable')
        return False, lines
    lines.append(f'  stažení: ok ({len(data)} B)')
    try:
        parsed = parse_ics(data, service.APP_TZ.key)
    except Exception:  # noqa: BLE001
        parsed = None
    if parsed is None or not parsed.complete:
        lines.append('  ICS: nelze přečíst (odpověď není platný kalendář – zneplatněná tajná adresa?)')
        return False, lines
    lines.append(f'  ICS: ok, událostí: {len(parsed.events)}, chybných: {parsed.errors}')
    return True, lines


def source_states() -> dict:
    """config_key → enabled from the database; empty when the database is not reachable."""
    try:
        import database
        from modules.calendar.models import CalendarSource
        db = database.SessionLocal()
        try:
            return {s.config_key: bool(s.enabled) for s in db.query(CalendarSource).all()}
        finally:
            db.close()
    except Exception:  # noqa: BLE001 - the feed check works without the database
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--env-file', type=Path, help='protected production env file (else the process environment)')
    parser.add_argument('--no-db', action='store_true', help='skip the source on/off state from the database')
    args = parser.parse_args(argv)
    if args.env_file:
        from production import load_production_environment
        load_production_environment(str(args.env_file))
    from modules.calendar import service

    states = {} if args.no_db else source_states()
    all_ok = True
    for key in service.SOURCES:
        try:
            ok, lines = check_source(key)
        except Exception:  # noqa: BLE001 - any unexpected error: category only, never a traceback with the URL
            ok, lines = False, [f'[{key}]', '  výsledek: chyba diagnostiky (detail se z bezpečnostních důvodů nevypisuje)']
        if key in states:
            lines.insert(1, f'  zdroj v Hubu: {"zapnutý" if states[key] else "VYPNUTÝ (source_disabled)"}')
            ok = ok and states[key]
        configured = not lines[-1].endswith('feed_not_configured')
        all_ok = all_ok and (ok or not configured)
        for line in lines:
            print(line)
    if not args.no_db and not states:
        print('Databáze nedostupná nebo bez zdrojů – stav zapnuto/vypnuto přeskočen.')
    return 0 if all_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
