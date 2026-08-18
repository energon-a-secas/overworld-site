"""Rate-limited Habitica API client.

Habitica allows 30 requests per minute and reports the budget back on every
response (`X-RateLimit-Remaining`, `X-RateLimit-Reset`). The limiter here is a
sliding window rather than a fixed one, because a fixed window lets 60 requests
through across a boundary and earns a 429 that costs more than the wait.

Mutating verbs are refused unless the client was built with dry_run=False. That
is the gate behind `hbx apply --apply`: the default path can talk to Habitica to
*read* what it would change, and physically cannot write.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

BASE_URL = 'https://habitica.com/api/v3'
MUTATING = ('POST', 'PUT', 'DELETE')


class ApiError(RuntimeError):
    def __init__(self, status, message, url):
        super().__init__('{} {} -> {}'.format(status, url, message))
        self.status = status
        self.url = url


class DryRunViolation(RuntimeError):
    """A mutating call was attempted on a dry-run client. Always a bug, never a warning."""


class RateLimiter:
    """Sliding-window limiter. `throttled` counts how often it actually slept.

    A limiter whose counter never moves has not been shown to work, so the
    counter is part of the contract and is asserted on in the tests.
    """

    def __init__(self, max_per_window=30, window=60.0, clock=time.monotonic, sleeper=time.sleep):
        self.max_per_window = max_per_window
        self.window = window
        self._clock = clock
        self._sleep = sleeper
        self._calls = deque()
        self.throttled = 0
        self.total_slept = 0.0

    def _evict(self, now):
        while self._calls and now - self._calls[0] >= self.window:
            self._calls.popleft()

    def acquire(self):
        now = self._clock()
        self._evict(now)
        if len(self._calls) >= self.max_per_window:
            wait = self.window - (now - self._calls[0])
            if wait > 0:
                self.throttled += 1
                self.total_slept += wait
                self._sleep(wait)
                now = self._clock()
                self._evict(now)
        self._calls.append(now)

    def pause_until_reset(self, seconds):
        """Server said 429. Trust it over the local window."""
        if seconds > 0:
            self.throttled += 1
            self.total_slept += seconds
            self._sleep(seconds)
        self._calls.clear()


class HabiticaClient:
    def __init__(self, user_id, api_token, app_name='Overworld', base_url=BASE_URL,
                 limiter=None, dry_run=True, timeout=30):
        self.user_id = user_id
        self._token = api_token
        self.base_url = base_url.rstrip('/')
        self.limiter = limiter or RateLimiter()
        self.dry_run = dry_run
        self.timeout = timeout
        # Habitica's third-party guideline: "<UserID>-<AppName>". auth.js can enforce presence.
        self.client_header = '{}-{}'.format(user_id, app_name)
        self.request_log = []      # (method, path) actually sent
        self.suppressed_log = []   # (method, path) refused by dry-run
        self.rate_remaining = None
        self.rate_reset = None

    def _headers(self):
        return {
            'x-api-user': self.user_id,
            'x-api-key': self._token,
            'x-client': self.client_header,
            'content-type': 'application/json',
            'accept': 'application/json',
        }

    def request(self, method, path, params=None, body=None, _retries=2):
        method = method.upper()
        if method in MUTATING and self.dry_run:
            self.suppressed_log.append((method, path))
            raise DryRunViolation(
                '{} {} attempted on a dry-run client. Pass --apply to allow writes.'
                .format(method, path))

        url = self.base_url + path
        if params:
            url += '?' + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None})

        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        for key, value in self._headers().items():
            req.add_header(key, value)

        self.limiter.acquire()
        self.request_log.append((method, path))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self._record_budget(resp.headers)
                payload = json.loads(resp.read().decode('utf-8') or '{}')
        except urllib.error.HTTPError as exc:
            self._record_budget(exc.headers)
            if exc.code == 429 and _retries > 0:
                retry_after = exc.headers.get('Retry-After')
                self.limiter.pause_until_reset(float(retry_after) if retry_after else 60.0)
                return self.request(method, path, params, body, _retries - 1)
            detail = exc.read().decode('utf-8', 'replace')[:400]
            raise ApiError(exc.code, detail, url) from None

        if isinstance(payload, dict) and payload.get('success') is False:
            raise ApiError(200, payload.get('message', 'request reported failure'), url)
        return payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload

    def _record_budget(self, headers):
        remaining = headers.get('X-RateLimit-Remaining')
        if remaining is not None:
            try:
                self.rate_remaining = int(remaining)
            except ValueError:
                pass
        self.rate_reset = headers.get('X-RateLimit-Reset')

    # -- reads ------------------------------------------------------------
    def get_user(self):
        return self.request('GET', '/user')

    def get_tasks(self, task_type=None, with_history=True):
        return self.request('GET', '/tasks/user', params={
            'type': task_type,
            'history': 'true' if with_history else 'false',
        })

    def get_tags(self):
        return self.request('GET', '/tags')

    # -- writes (blocked unless dry_run=False) ----------------------------
    def create_tag(self, name):
        return self.request('POST', '/tags', body={'name': name})

    def rename_tag(self, tag_id, name):
        return self.request('PUT', '/tags/{}'.format(tag_id), body={'name': name})

    def delete_tag(self, tag_id):
        return self.request('DELETE', '/tags/{}'.format(tag_id))

    def add_tag_to_task(self, task_id, tag_id):
        return self.request('POST', '/tasks/{}/tags/{}'.format(task_id, tag_id))

    def remove_tag_from_task(self, task_id, tag_id):
        return self.request('DELETE', '/tasks/{}/tags/{}'.format(task_id, tag_id))

    def create_todo(self, text, notes='', tags=None, date=None, priority=None):
        body = {'type': 'todo', 'text': text, 'notes': notes}
        if tags:
            body['tags'] = tags
        if date:
            body['date'] = date
        if priority:
            body['priority'] = priority
        return self.request('POST', '/tasks/user', body=body)
