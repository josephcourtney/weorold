from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from weorold.errors import DataSourceError

type QueryValue = str | int | float | Sequence[str | int | float]
type QueryParams = Mapping[str, QueryValue]
type HttpHeaders = Mapping[str, str]


class HttpGetter(Protocol):
    def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: HttpHeaders | None = None,
        ttl_s: float | None = None,
    ) -> bytes: ...


class HttpPoster(Protocol):
    def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: HttpHeaders | None = None,
        ttl_s: float | None = None,
    ) -> bytes: ...


class HttpClient(HttpGetter, HttpPoster, Protocol):
    pass


@dataclass(slots=True)
class CachedHttpClient:
    """Small synchronous HTTP client with an optional file cache.

    Data retrieval is intentionally kept outside the simulation packages.  The
    cache is URL-addressed and safe for concurrent readers; writers replace cache
    entries atomically.
    """

    user_agent: str = "weorold/0.4"
    timeout_s: float = 30.0
    cache_dir: Path | None = None
    default_ttl_s: float = 3600.0
    max_retries: int = 2
    retry_backoff_s: float = 0.5

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.default_ttl_s < 0:
            raise ValueError("default_ttl_s must be non-negative")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_s < 0:
            raise ValueError("retry_backoff_s must be non-negative")
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _encoded_url(
        url: str,
        params: Mapping[str, str | int | float | Sequence[str | int | float]] | None,
    ) -> str:
        if not params:
            return url
        encoded = urlencode(params, doseq=True)
        return f"{url}{'&' if '?' in url else '?'}{encoded}"

    def _cache_path(self, full_url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(full_url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.cache"

    @staticmethod
    def _cacheable(headers: HttpHeaders | None) -> bool:
        """Return whether a request may use the persistent response cache."""

        # Authenticated representations are not cached by default. Add an
        # explicit cache identity only when a provider demonstrates a safe need
        # for authenticated caching.
        return not any(name.lower() == "authorization" for name in (headers or {}))

    @staticmethod
    def _cache_fresh(path: Path, ttl_s: float) -> bool:
        if ttl_s <= 0 or not path.exists():
            return False
        return time.time() - path.stat().st_mtime <= ttl_s

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            temporary = Path(tmp.name)
        temporary.replace(path)

    def get(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: HttpHeaders | None = None,
        ttl_s: float | None = None,
    ) -> bytes:
        full_url = self._encoded_url(url, params)
        effective_ttl = self.default_ttl_s if ttl_s is None else ttl_s
        cache_path = self._cache_path(full_url) if self._cacheable(headers) else None
        if cache_path is not None and self._cache_fresh(cache_path, effective_ttl):
            return cache_path.read_bytes()

        request_headers = {
            "Accept-Encoding": "identity",
            "User-Agent": self.user_agent,
            **dict(headers or {}),
        }
        request = Request(full_url, headers=request_headers, method="GET")
        payload: bytes | None = None
        retryable_status = {429, 500, 502, 503, 504}
        for attempt in range(self.max_retries + 1):
            try:
                # Adapters provide the URLs; callers are responsible for trusted endpoints.
                with urlopen(request, timeout=self.timeout_s) as response:
                    payload = response.read()
                break
            except HTTPError as exc:
                can_retry = exc.code in retryable_status and attempt < self.max_retries
                if can_retry:
                    retry_after = (
                        exc.headers.get("Retry-After") if exc.headers is not None else None
                    )
                    try:
                        delay = float(retry_after) if retry_after is not None else None
                    except ValueError:
                        delay = None
                    time.sleep(delay if delay is not None else self.retry_backoff_s * (2**attempt))
                    continue
                detail = exc.read(2048).decode("utf-8", errors="replace")
                raise DataSourceError(f"HTTP {exc.code} retrieving {url}: {detail[:300]}") from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * (2**attempt))
                    continue
                raise DataSourceError(f"failed retrieving {url}: {exc.reason}") from exc
        if payload is None:  # pragma: no cover - loop either succeeds or raises
            raise DataSourceError(f"failed retrieving {url}")

        if cache_path is not None:
            self._atomic_write(cache_path, payload)
        return payload

    def post(
        self,
        url: str,
        *,
        body: bytes,
        headers: HttpHeaders | None = None,
        ttl_s: float | None = None,
    ) -> bytes:
        effective_ttl = self.default_ttl_s if ttl_s is None else ttl_s
        cache_path = None

        if self.cache_dir is not None and self._cacheable(headers):
            digest_input = url.encode("utf-8") + b"\0" + body
            digest = hashlib.sha256(digest_input).hexdigest()
            cache_path = self.cache_dir / f"{digest}.cache"

        if cache_path is not None and self._cache_fresh(cache_path, effective_ttl):
            return cache_path.read_bytes()

        request_headers = {
            "Accept-Encoding": "identity",
            "User-Agent": self.user_agent,
            **dict(headers or {}),
        }
        request = Request(url, data=body, headers=request_headers, method="POST")
        payload: bytes | None = None
        retryable_status = {429, 500, 502, 503, 504}
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_s) as response:
                    payload = response.read()
                break
            except HTTPError as exc:
                if exc.code in retryable_status and attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * (2**attempt))
                    continue
                detail = exc.read(2048).decode("utf-8", errors="replace")
                raise DataSourceError(f"HTTP {exc.code} posting to {url}: {detail[:300]}") from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff_s * (2**attempt))
                    continue
                raise DataSourceError(f"failed posting to {url}: {exc.reason}") from exc
        if payload is None:  # pragma: no cover
            raise DataSourceError(f"failed posting to {url}")
        if cache_path is not None:
            self._atomic_write(cache_path, payload)
        return payload

    def get_json(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: HttpHeaders | None = None,
        ttl_s: float | None = None,
    ) -> object:
        payload = self.get(url, params=params, headers=headers, ttl_s=ttl_s)
        try:
            return json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DataSourceError(f"invalid JSON returned by {url}") from exc
