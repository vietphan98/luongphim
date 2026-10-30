from __future__ import annotations
import itertools, time
from dataclasses import dataclass, field, asdict
from typing import Optional

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
_ids = itertools.count(1)


@dataclass
class Job:
    prompt: str
    duration: float = 5
    aspect: str = "16:9"
    provider: str = "mock"
    character: Optional[str] = None
    name: Optional[str] = None
    id: str = field(default_factory=lambda: f"job{next(_ids):03d}")
    status: str = QUEUED
    progress: float = 0.0
    attempts: int = 0
    error: Optional[str] = None
    output: Optional[str] = None
    thumb: Optional[str] = None
    effective_provider: Optional[str] = None
    note: Optional[str] = None
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_spec(cls, spec: dict, defaults: dict | None = None) -> "Job":
        d = dict(defaults or {})
        d.update(spec)
        if not d.get("prompt"):
            raise ValueError(f"job thiếu 'prompt': {spec}")
        allowed = {"prompt", "duration", "aspect", "provider", "character", "name"}
        unknown = set(d) - allowed
        if unknown:
            raise ValueError(f"trường không hỗ trợ: {sorted(unknown)}")
        d["duration"] = float(d.get("duration", 5))
        return cls(**d)


class ProviderError(Exception):
    """Lỗi từ provider. retryable=True nghĩa là nên thử lại."""
    def __init__(self, msg, retryable=True):
        super().__init__(msg)
        self.retryable = retryable


class RateLimitError(ProviderError):
    def __init__(self, msg="rate limited", retry_after: float | None = None):
        super().__init__(msg, retryable=True)
        self.retry_after = retry_after
