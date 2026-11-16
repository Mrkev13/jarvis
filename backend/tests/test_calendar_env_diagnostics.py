"""MRK-103: Google/Moodle ICS address in quotes (Docker `env_file` format: raw) and the read-only source diagnostic."""
import os
import sys

import pytest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for path in (BACKEND_DIR, os.path.join(BACKEND_DIR, 'scripts')):
    if path not in sys.path:
        sys.path.insert(0, path)

import check_calendar_sources as diag  # noqa: E402
from modules.calendar import service  # noqa: E402

GOOGLE_URL = 'https://calendar.google.com/calendar/ical/x%40group/private-google-secret-canary/basic.ics'
MOODLE_URL = 'https://moodle.example.invalid/export?token=moodle-secret-canary'
ICS = (b'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic//EN\r\nBEGIN:VEVENT\r\nUID:a@google\r\nSUMMARY:Zubar\r\n'
       b'DTSTART:20261012T070000Z\r\nDTEND:20261012T080000Z\r\nDTSTAMP:20261001T000000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n')


@pytest.mark.parametrize('raw', [f'"{GOOGLE_URL}"', f"'{GOOGLE_URL}'", f'  "{GOOGLE_URL}"  ', f'" {GOOGLE_URL} "'])
def test_quoted_feed_url_is_unquoted(monkeypatch, raw):
    """Regression: with `format: raw` the quotes reach the process; the sync then failed as invalid_feed_configuration."""
    monkeypatch.setenv('GOOGLE_ICS_URL', raw)
    assert service.feed_url('google') == GOOGLE_URL
    seen = []

    def fetch(url):  # the real sync path hands the unquoted URL to the fetcher
        seen.append(url)
        raise service.CalendarSyncError('feed_unavailable')

    with pytest.raises(service.CalendarSyncError) as error:
        service.sync_source(_NoDb(), 'google', fetch=fetch)
    assert seen == [GOOGLE_URL] and error.value.category == 'feed_unavailable'


@pytest.mark.parametrize('raw', ['"https://x.example/a', 'https://x.example/"a"', '"', "''"])
def test_unmatched_or_inner_quotes_are_left_alone(monkeypatch, raw):
    monkeypatch.setenv('GOOGLE_ICS_URL', raw)
    # a lone quote or an inner quote stays (fails later as invalid_feed_configuration); '' is just empty
    assert service.feed_url('google') == ('' if raw == "''" else raw)


def test_quoted_url_was_invalid_before_unquoting():
    """What production saw: the literal quoted value is rejected by fetch_feed without any network access."""
    with pytest.raises(service.CalendarSyncError) as error:
        service.fetch_feed(f'"{GOOGLE_URL}"')
    assert error.value.category == 'invalid_feed_configuration'


class _NoDb:
    """sync_source only touches the DB after a successful fetch; these tests stop before that."""

    def query(self, *_a, **_k):
        return self

    def filter_by(self, **_k):
        return self

    def one_or_none(self):
        return None


# ---------- diagnostic script: status lines only ----------

def _run(env, **kw):
    return diag.check_source('google', env, resolve=kw.get('resolve', lambda *_a: [()]), fetch=kw.get('fetch', lambda url: ICS))


def _assert_no_secret(lines):
    text = '\n'.join(lines)
    assert 'canary' not in text and 'calendar.google.com/calendar' not in text and 'moodle.example' not in text


def test_diagnostic_ok_with_quotes_reports_quotes_and_events():
    ok, lines = _run({'GOOGLE_ICS_URL': f'"{GOOGLE_URL}"'})
    assert ok
    text = '\n'.join(lines)
    assert 'uvozovky kolem hodnoty: ano' in text and 'host odpovídá calendar.google.com: ano' in text
    assert 'DNS: ok' in text and 'ICS: ok, událostí: 1' in text
    _assert_no_secret(lines)


def test_diagnostic_not_configured():
    ok, lines = _run({})
    assert not ok and lines[-1].endswith('feed_not_configured')


def test_diagnostic_dns_failure():
    def resolve(*_a):
        raise OSError(f'cannot resolve {GOOGLE_URL}')
    ok, lines = _run({'GOOGLE_ICS_URL': GOOGLE_URL}, resolve=resolve)
    assert not ok and 'DNS: selhalo' in lines[-1]
    _assert_no_secret(lines)


@pytest.mark.parametrize('error, expected', [
    (service.CalendarSyncError('feed_redirect_rejected'), 'stažení: feed_redirect_rejected'),
    (RuntimeError(f'HTTP 404 for {GOOGLE_URL}'), 'stažení: feed_unavailable'),
])
def test_diagnostic_download_failure_prints_category_only(error, expected):
    def fetch(url):
        raise error
    ok, lines = _run({'GOOGLE_ICS_URL': GOOGLE_URL}, fetch=fetch)
    assert not ok and lines[-1] == f'  {expected}'
    _assert_no_secret(lines)


def test_diagnostic_invalid_ics_and_bad_scheme():
    ok, lines = _run({'GOOGLE_ICS_URL': GOOGLE_URL}, fetch=lambda url: b'<html>not a calendar</html>')
    assert not ok and 'ICS: nelze přečíst' in lines[-1]
    ok, lines = _run({'GOOGLE_ICS_URL': GOOGLE_URL.replace('https', 'http')})
    assert not ok and 'invalid_feed_configuration' in lines[-1]
    _assert_no_secret(lines)


def test_diagnostic_main_never_prints_urls(monkeypatch, capsys):
    monkeypatch.setenv('GOOGLE_ICS_URL', f"'{GOOGLE_URL}'")
    monkeypatch.setenv('MOODLE_ICS_URL', MOODLE_URL)
    monkeypatch.setattr(service, 'fetch_feed', lambda url: ICS)
    monkeypatch.setattr(diag.socket, 'getaddrinfo', lambda *_a: [()])
    assert diag.main(['--no-db']) == 0
    out = capsys.readouterr().out
    assert '[google]' in out and '[moodle]' in out
    _assert_no_secret(out.splitlines())
