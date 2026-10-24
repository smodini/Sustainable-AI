"""Scripted fake of a ``requests.Session`` for collector tests (no network)."""
from __future__ import annotations

from typing import Any, Callable

from app.providers.rest import RestClient


class FakeResponse:
    def __init__(self, status: int = 200, body: Any = None, headers: dict | None = None):
        self.status_code, self._body, self.headers = status, body if body is not None else {}, headers or {}
        self.text = str(self._body)

    def json(self) -> Any:
        return self._body


class FakeSession:
    """``handler(url, params) -> FakeResponse | dict``; records every call."""

    def __init__(self, handler: Callable[[str, dict], Any]):
        self.handler, self.calls = handler, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        out = self.handler(url, dict(params or {}))
        return out if isinstance(out, FakeResponse) else FakeResponse(200, out)


def rest_with(handler, **kw) -> tuple[RestClient, FakeSession]:
    session = FakeSession(handler)
    sleeps: list[float] = []
    client = RestClient(lambda: "tok", session=session, sleep=sleeps.append, **kw)
    client.sleeps = sleeps  # type: ignore[attr-defined]
    return client, session
