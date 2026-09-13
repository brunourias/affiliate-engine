from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityResult:
    key: str
    status: str
    endpoint: str | None
    http_status: int | None = None
    latency_ms: int | None = None
    reason_code: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    data: Any = None
