from __future__ import annotations
import asyncio, base64, json, mimetypes, os, urllib.error, urllib.request
from pathlib import Path
from ..models import ProviderError, RateLimitError

ASPECTS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960), "4:3": (960, 720), "3:4": (720, 960)}


class Provider:
    name = "base"
    env_key: str | None = None
    supports_reference = False
    max_concurrency = 2
    poll_interval = 5.0
    timeout = 900.0

    def __init__(self, api_key=None, max_concurrency=None, **opts):
        self.api_key = api_key or (os.environ.get(self.env_key) if self.env_key else None)
        if max_concurrency:
            self.max_concurrency = int(max_concurrency)
        self.opts = opts

    @classmethod
    def available(cls):
        return cls.env_key is None or bool(os.environ.get(cls.env_key))

    async def generate(self, job, refs, dest: Path, progress):
        raise NotImplementedError

    # ---- tiện ích HTTP (stdlib, chạy trong thread) ----
    def _request(self, method, url, headers=None, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "User-Agent": "luongphim/0.1"}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                content = r.read()
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")[:500]
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                raise RateLimitError(f"{self.name} 429: {txt}", float(ra) if ra and ra.replace('.', '', 1).isdigit() else None)
            raise ProviderError(f"{self.name} HTTP {e.code}: {txt}", retryable=e.code >= 500)
        except urllib.error.URLError as e:
            raise ProviderError(f"{self.name} mạng lỗi: {e}", retryable=True)
        return content if raw else (json.loads(content) if content else {})

    async def http(self, method, url, headers=None, body=None, raw=False):
        return await asyncio.to_thread(self._request, method, url, headers, body, raw)

    async def download(self, url, dest, headers=None):
        data = await self.http("GET", url, headers=headers, raw=True)
        Path(dest).write_bytes(data)

    async def poll(self, fn, progress, est=120.0):
        """Gọi fn() tới khi trả về khác None; ước lượng % theo thời gian (API thường không trả %)."""
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        while True:
            res = await fn()
            if res is not None:
                return res
            el = loop.time() - t0
            if el > self.timeout:
                raise ProviderError(f"{self.name}: quá thời gian chờ", retryable=True)
            progress(min(95.0, 95.0 * el / (el + est)) if est else 50)
            await asyncio.sleep(self.poll_interval)


def data_uri(path):
    if str(path).startswith(("http://", "https://")):
        return str(path)
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode(), mimetypes.guess_type(str(path))[0] or "image/png"
