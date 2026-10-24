from app.providers.rest import CachedToken, RestError
from tests.fake_http import FakeResponse, rest_with


def test_retries_429_honouring_retry_after_then_succeeds():
    seq = [FakeResponse(429, {}, {"Retry-After": "3"}), FakeResponse(503), {"ok": True}]
    rest, session = rest_with(lambda u, p: seq.pop(0))
    assert rest.get_json("https://x/y") == {"ok": True}
    assert rest.sleeps[0] == 3.0 and rest.sleeps[1] == 2.0  # header, then exponential backoff
    assert all(c[2]["Authorization"] == "Bearer tok" for c in session.calls)


def test_non_retryable_status_raises_immediately():
    rest, session = rest_with(lambda u, p: FakeResponse(403, {"error": "denied"}))
    try:
        rest.get_json("https://x/y")
    except RestError as exc:
        assert exc.status == 403 and len(session.calls) == 1 and rest.sleeps == []
        return
    raise AssertionError("expected RestError")


def test_retries_exhausted_raises():
    rest, session = rest_with(lambda u, p: FakeResponse(500), max_attempts=3)
    try:
        rest.get_json("https://x/y")
    except RestError as exc:
        assert exc.status == 500 and len(session.calls) == 3 and len(rest.sleeps) == 2
        return
    raise AssertionError("expected RestError")


def test_paginate_token_style_sends_page_token():
    pages = {None: {"a": 1, "nextPageToken": "T2"}, "T2": {"a": 2}}
    rest, session = rest_with(lambda u, p: pages[p.get("pageToken")])
    assert [pg["a"] for pg in rest.paginate("https://x/y", {"q": "1"})] == [1, 2]
    assert session.calls[1][1] == {"q": "1", "pageToken": "T2"}


def test_paginate_next_link_style_follows_absolute_url():
    def handler(url, params):
        return {"v": 1, "nextLink": "https://x/page2?skip=1"} if url == "https://x/y" else {"v": 2}
    rest, session = rest_with(handler)
    assert [pg["v"] for pg in rest.paginate("https://x/y", {"api-version": "1"}, link_field="nextLink")] == [1, 2]
    assert session.calls[1][0] == "https://x/page2?skip=1" and session.calls[1][1] == {}


def test_cached_token_refreshes_only_near_expiry():
    now, fetched = [1000.0], []
    def fetch():
        fetched.append(1); return f"t{len(fetched)}", 2000.0
    tok = CachedToken(fetch, clock=lambda: now[0])
    assert tok() == "t1" and tok() == "t1" and len(fetched) == 1
    now[0] = 1750.0  # within 300 s of expiry
    assert tok() == "t2"
