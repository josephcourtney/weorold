from __future__ import annotations

from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from weorold.transport import CachedHttpClient
from weorold.errors import DataSourceError


def _headers(**values: str) -> Message:
    message = Message()
    for name, value in values.items():
        message[name.replace("_", "-")] = value
    return message


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    def read(self) -> bytes:
        return self.payload


def test_cached_http_client_reuses_fresh_response(monkeypatch, tmp_path):
    calls = 0

    def fake_urlopen(_request, *, timeout):
        nonlocal calls
        assert timeout == 3.0
        calls += 1
        return _Response(b"payload")

    monkeypatch.setattr("weorold.transport.urlopen", fake_urlopen)
    client = CachedHttpClient(cache_dir=tmp_path, timeout_s=3.0, max_retries=0)
    assert client.get("https://example.test/data", params={"x": 1}, ttl_s=60) == b"payload"
    assert client.get("https://example.test/data", params={"x": 1}, ttl_s=60) == b"payload"
    assert calls == 1


def test_cached_http_client_retries_transient_network_failure(monkeypatch):
    outcomes = [URLError("temporary"), _Response(b"ok")]

    def fake_urlopen(_request, *, timeout):
        del timeout
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("weorold.transport.urlopen", fake_urlopen)
    monkeypatch.setattr("weorold.transport.time.sleep", lambda _seconds: None)
    client = CachedHttpClient(max_retries=1, retry_backoff_s=0.0)
    assert client.get("https://example.test/data") == b"ok"
    assert outcomes == []


def test_cached_http_client_retries_http_error_with_invalid_retry_after(monkeypatch):
    retryable = HTTPError(
        "https://example.test/data",
        503,
        "busy",
        _headers(Retry_After="not-a-number"),
        BytesIO(b"busy"),
    )
    outcomes = [retryable, _Response(b"ok")]
    sleeps: list[float] = []

    def fake_urlopen(_request, *, timeout):
        del timeout
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("weorold.transport.urlopen", fake_urlopen)
    monkeypatch.setattr("weorold.transport.time.sleep", sleeps.append)
    client = CachedHttpClient(max_retries=1, retry_backoff_s=0.25)

    assert client.get("https://example.test/data") == b"ok"
    assert sleeps == [0.25]


def test_cached_http_client_surfaces_non_retryabld_http_error(monkeypatch):
    error = HTTPError(
        "https://example.test/missing",
        404,
        "missing",
        Message(),
        BytesIO(b"not found"),
    )

    def fake_urlopen(_request, *, timeout):
        del timeout
        raise error

    monkeypatch.setattr("weorold.transport.urlopen", fake_urlopen)
    client = CachedHttpClient(max_retries=2)

    with pytest.raises(DataSourceError, match=r"HTTP 404.*not found"):
        client.get("https://example.test/missing")


def test_cached_http_client_does_not_cache_authenticated_get(
    monkeypatch,
    tmp_path,
) -> None:
    calls = 0

    def fake_urlopen(_request, *, timeout):
        nonlocal calls
        del timeout
        calls += 1
        return _Response(f"value-{calls}".encode())

    monkeypatch.setattr("weorold.transport.urlopen", fake_urlopen)

    client = CachedHttpClient(
        cache_dir=tmp_path,
        max_retries=0,
    )

    first = client.get(
        "https://example.test/private",
        headers={"Authorization": "Bearer secret"},
    )
    second = client.get(
        "https://example.test/private",
        headers={"Authorization": "Bearer secret"},
    )

    assert first == b"value-1"
    assert second == b"value-2"
    assert calls == 2


def test_cached_http_client_does_not_cache_authenticated_post(
    monkeypatch,
    tmp_path,
) -> None:
    calls = 0

    def fake_urlopen(_request, *, timeout):
        nonlocal calls
        del timeout
        calls += 1
        return _Response(f"value-{calls}".encode())

    monkeypatch.setattr("weorold.transport.urlopen", fake_urlopen)

    client = CachedHttpClient(
        cache_dir=tmp_path,
        max_retries=0,
    )

    headers = {"Authorization": "Bearer secret"}

    first = client.post(
        "https://example.test/private",
        body=b"request",
        headers=headers,
    )
    second = client.post(
        "https://example.test/private",
        body=b"request",
        headers=headers,
    )

    assert first == b"value-1"
    assert second == b"value-2"
    assert calls == 2
