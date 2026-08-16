from __future__ import annotations

import json
from collections.abc import Callable, Mapping

type ResponseProvider = Mapping[str, object] | Callable[[str, object], object]


class FakeHttp:
    def __init__(
        self,
        responses: ResponseProvider,
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[str, object]] = []

    def get(
        self,
        url: str,
        *,
        params=None,
        headers=None,
        ttl_s=None,
    ) -> bytes:
        del headers, ttl_s
        self.calls.append((url, params))

        responses = self.responses
        value = responses[url] if isinstance(responses, Mapping) else responses(url, params)

        return value if isinstance(value, bytes) else json.dumps(value).encode()
