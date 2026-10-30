from .base import Provider
from .mock import MockProvider
from .replicate import ReplicateProvider
from .fal import FalProvider
from .runway import RunwayProvider
from .luma import LumaProvider
from .veo import VeoProvider

REGISTRY = {c.name: c for c in (MockProvider, ReplicateProvider, FalProvider, RunwayProvider, LumaProvider, VeoProvider)}


def build_providers(names, force_mock=False, config=None, mock_opts=None):
    """Tạo dict tên -> provider. Provider thiếu key (hoặc force_mock) được thay bằng mock."""
    config = config or {}
    out, fallback = {}, []
    for n in set(names) | {"mock"}:
        cls = REGISTRY.get(n)
        if cls is None:
            continue
        if n == "mock" or force_mock or not cls.available():
            m = MockProvider(**{**(mock_opts or {}), **config.get("mock", {})})
            if n != "mock":
                m.name = f"mock({n})"
                m.max_concurrency = config.get(n, {}).get("max_concurrency", cls.max_concurrency)
                fallback.append(n)
            out[n] = m
        else:
            out[n] = cls(**config.get(n, {}))
    return out, fallback
