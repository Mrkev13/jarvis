"""Official Moodle Web Services client (MRK-42) – REST protocol, JSON format, no HTML scraping.

Uses only documented functions available to the Moodle mobile web service:
`core_webservice_get_site_info` (own user id), `core_enrol_get_users_courses` (enrolled courses) and
`core_course_get_contents` (sections → modules → file contents). Files come from the `fileurl` the API returns
(`/webservice/pluginfile.php/...`), fetched only from the configured origin.

Secret handling: the token is sent only in the POST body (never in a URL, header or log line). Every network or
decoding exception is discarded and replaced with an allowlisted category, because urllib/JSON errors can echo the
request (token) or a signed file URL. Nothing here logs. The configured base URL and token stay server-side;
the frontend only ever sees `configured: true/false`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from env_config import env_int, env_str

MAX_JSON_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 20
WS_PATH = '/webservice/rest/server.php'
FILE_PATH_PREFIX = '/webservice/pluginfile.php/'
AUTH_ERRORS = frozenset({'invalidtoken', 'accessexception', 'servicerequireslogin', 'usernotfullysetup',
                         'invalidlogin', 'forcepasswordchangenotice', 'sitemaintenance'})


class MoodleSyncError(Exception):
    """Allowlisted, secret-free failure category (→ API 503 / sync stats). Never carries upstream text."""
    CATEGORIES = frozenset({'not_configured', 'invalid_configuration', 'unavailable', 'redirect_rejected',
                            'auth_failed', 'ws_error', 'response_invalid', 'response_too_large',
                            'file_too_large', 'file_unavailable', 'file_url_rejected'})

    def __init__(self, category: str = 'unavailable'):
        self.category = category if category in self.CATEGORIES else 'unavailable'
        super().__init__(self.category)


@dataclass(frozen=True)
class MoodleConfig:
    base_url: str
    token: str
    max_file_bytes: int


def max_file_bytes() -> int:
    return min(env_int('MOODLE_MAX_FILE_MB', 25, minimum=1), 100) * 1024 * 1024


def load_config() -> MoodleConfig | None:
    """Server-side configuration from env only; None when not configured."""
    base, token = env_str('MOODLE_WS_BASE_URL').rstrip('/'), env_str('MOODLE_WS_TOKEN')
    if not base or not token:
        return None
    return MoodleConfig(base, token, max_file_bytes())


def is_configured() -> bool:
    return load_config() is not None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MoodleSyncError('redirect_rejected')


def _origin(url: str):
    parts = urlsplit(url)
    return parts.scheme, (parts.hostname or '').lower(), parts.port


class MoodleWsClient:
    """`opener` is injectable for tests (anything with `.open(request, timeout=)`); default = urllib, TLS
    verified, redirects refused."""

    def __init__(self, config: MoodleConfig, *, opener=None):
        parts = urlsplit(config.base_url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query
                or parts.fragment):
            raise MoodleSyncError('invalid_configuration')
        self._config = config
        self._opener = opener or build_opener(_NoRedirect(), HTTPSHandler(debuglevel=0))
        self._user_id = None

    def _post(self, url: str, fields: dict, limit: int) -> bytes:
        try:
            body = urlencode(fields).encode('ascii')
            request = Request(url, data=body, method='POST',
                              headers={'Content-Type': 'application/x-www-form-urlencoded'})
            with self._opener.open(request, timeout=TIMEOUT_S) as response:
                data = response.read(limit + 1)
        except MoodleSyncError:
            raise
        except Exception:
            # urllib errors may contain the request; never re-raise or chain them
            raise MoodleSyncError('unavailable') from None
        if len(data) > limit:
            raise MoodleSyncError('response_too_large')
        return data

    def _call(self, function: str, **params):
        data = self._post(self._config.base_url + WS_PATH,
                          {'wstoken': self._config.token, 'wsfunction': function, 'moodlewsrestformat': 'json',
                           **params}, MAX_JSON_BYTES)
        try:
            result = json.loads(data.decode('utf-8'))
        except Exception:
            raise MoodleSyncError('response_invalid') from None
        if isinstance(result, dict) and ('exception' in result or 'errorcode' in result):
            code = result.get('errorcode')
            raise MoodleSyncError('auth_failed' if isinstance(code, str) and code in AUTH_ERRORS else 'ws_error')
        return result

    def user_id(self) -> int:
        if self._user_id is None:
            info = self._call('core_webservice_get_site_info')
            uid = info.get('userid') if isinstance(info, dict) else None
            if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0:
                raise MoodleSyncError('response_invalid')
            self._user_id = uid
        return self._user_id

    def courses(self) -> list:
        result = self._call('core_enrol_get_users_courses', userid=self.user_id())
        if not isinstance(result, list):
            raise MoodleSyncError('response_invalid')
        return result

    def course_contents(self, course_id: str) -> list:
        result = self._call('core_course_get_contents', courseid=course_id)
        if not isinstance(result, list):
            raise MoodleSyncError('response_invalid')
        return result

    def download(self, file_url: str, max_bytes: int) -> bytes:
        """Only `/webservice/pluginfile.php/` on the configured origin; token in the POST body."""
        if not isinstance(file_url, str):
            raise MoodleSyncError('file_url_rejected')
        parts = urlsplit(file_url)
        if (_origin(file_url) != _origin(self._config.base_url) or parts.username or parts.password
                or not parts.path.startswith(FILE_PATH_PREFIX) or '..' in parts.path.split('/')):
            raise MoodleSyncError('file_url_rejected')
        # drop any query (a returned URL may already carry a token/signature); token goes in the body
        clean = f'{parts.scheme}://{parts.netloc}{parts.path}'
        try:
            return self._post(clean, {'token': self._config.token}, max_bytes)
        except MoodleSyncError as error:
            if error.category == 'response_too_large':
                raise MoodleSyncError('file_too_large') from None
            if error.category in ('unavailable', 'redirect_rejected'):
                raise MoodleSyncError('file_unavailable') from None
            raise
