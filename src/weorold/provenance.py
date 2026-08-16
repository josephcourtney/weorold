from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceRecord:
    name: str
    endpoint: str
    retrieved_at: datetime
    details: dict[str, Any] = field(default_factory=dict)
