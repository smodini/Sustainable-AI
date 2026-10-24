"""Minimal authenticated JSON-over-REST client shared by the GCP and Azure collectors.

Both clouds expose Compute inventory and monitoring over plain REST returning the same
camelCase JSON the normalizers consume, so one small client covers them. It adds what a
production scan needs and a bare ``requests.get`` does not: bearer-token refresh,
retry with backoff on 429/5xx (honouring ``Retry-After``), and pagination.

``requests`` is imported lazily and the HTTP session, token function and sleep are
injectable, so everything here is exercised in tests with fakes and no network.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterator, Optional

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class RestError(RuntimeError):
    """A non-retryable (or retries-exhausted) HTTP failure."""

    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} from {url}: {body[:300]}")
        self.status = status
        self.url = url


class RestClient:
    def __init__(
        self,
        get_token: Callable[[], str],
        session: Any | None = None,
        max_attempts: int = 6,
        base_delay_s: float = 1.0,
        max_delay_s: float = 30.0,
        timeout_s: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._get_token = get_token
        self._session = session
        self._max_attempts = max_attempts
        self._base_delay = base_delay_s
        self._max_delay = max_delay_s
        self._timeout = timeout_s
        self._sleep = sleep

    @property
    def session(self) -> Any:
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _delay(self, attempt: int, retry_after: Optional[str]) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self._max_delay)
            except ValueError:
                pass
        return min(self._base_delay * (2**attempt), self._max_delay)

    def get_json(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        last_status, last_body = 0, ""
        for attempt in range(self._max_attempts):
            # Token fetched per attempt: the callable caches and refreshes it, so a long
            # scan never presents an expired token.
            resp = self.session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=self._timeout,
            )
            if resp.status_code < 400:
                return resp.json()
            last_status, last_body = resp.status_code, getattr(resp, "text", "")
            if resp.status_code not in RETRYABLE_STATUS:
                raise RestError(resp.status_code, url, last_body)
            if attempt < self._max_attempts - 1:
                delay = self._delay(attempt, resp.headers.get("Retry-After"))
                log.warning("HTTP %s from %s; retrying in %.1fs", resp.status_code, url, delay)
                self._sleep(delay)
        raise RestError(last_status, url, last_body)

    def paginate(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        *,
        token_param: str = "pageToken",
        token_field: str = "nextPageToken",
        link_field: Optional[str] = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every page. GCP style: send ``token_param`` and read ``token_field``.
        Azure ARM style: set ``link_field="nextLink"`` and follow the absolute URL."""
        page = self.get_json(url, params)
        yield page
        while True:
            if link_field:
                link = page.get(link_field)
                if not link:
                    return
                page = self.get_json(link)  # nextLink already carries every query parameter
            else:
                token = page.get(token_field)
                if not token:
                    return
                page = self.get_json(url, {**(params or {}), token_param: token})
            yield page


class CachedToken:
    """Wraps a ``fetch() -> (token, expires_at_epoch)`` callable; refreshes 5 min early."""

    def __init__(self, fetch: Callable[[], tuple[str, float]], clock: Callable[[], float] = time.time):
        self._fetch, self._clock = fetch, clock
        self._token: Optional[str] = None
        self._expires = 0.0

    def __call__(self) -> str:
        if self._token is None or self._clock() >= self._expires - 300:
            self._token, self._expires = self._fetch()
        return self._token
