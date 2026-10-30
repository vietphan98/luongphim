from .base import Provider
from ..models import ProviderError


class LumaProvider(Provider):
    """Luma Dream Machine API: POST /dream-machine/v1/generations, poll GET /generations/{id}.
    Keyframe ảnh phải là URL công khai -> chỉ dùng ảnh nhân vật dạng http(s)."""
    name = "luma"
    env_key = "LUMAAI_API_KEY"
    supports_reference = True
    max_concurrency = 2
    BASE = "https://api.lumalabs.ai/dream-machine/v1"

    async def generate(self, job, refs, dest, progress):
        h = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        body = {"prompt": job.prompt, "model": self.opts.get("model", "ray-2"),
                "aspect_ratio": job.aspect, "duration": "9s" if job.duration > 7 else "5s"}
        url_refs = [r for r in refs if r.startswith("http")]
        if url_refs:
            body["keyframes"] = {"frame0": {"type": "image", "url": url_refs[0]}}
        elif refs:
            job.note = "luma cần URL ảnh công khai; ảnh local bị bỏ qua"
        g = await self.http("POST", f"{self.BASE}/generations", h, body)

        async def check():
            s = await self.http("GET", f"{self.BASE}/generations/{g['id']}", h)
            if s["state"] == "completed":
                return s
            if s["state"] == "failed":
                raise ProviderError(f"luma: {s.get('failure_reason')}", retryable=False)
        s = await self.poll(check, progress, est=120)
        await self.download(s["assets"]["video"], dest)
