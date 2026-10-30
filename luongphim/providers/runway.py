from .base import Provider, data_uri
from ..models import ProviderError

RATIOS = {"16:9": "1280:720", "9:16": "720:1280", "1:1": "960:960", "4:3": "1104:832", "3:4": "832:1104"}


class RunwayProvider(Provider):
    """Runway API: POST /v1/image_to_video (X-Runway-Version), poll /v1/tasks/{id}.
    Model gen4_turbo BẮT BUỘC có ảnh đầu vào -> job không có nhân vật sẽ bị từ chối."""
    name = "runway"
    env_key = "RUNWAYML_API_SECRET"
    supports_reference = True
    max_concurrency = 2
    BASE = "https://api.dev.runwayml.com/v1"

    async def generate(self, job, refs, dest, progress):
        if not refs:
            raise ProviderError("runway gen4_turbo cần ảnh tham chiếu (character)", retryable=False)
        h = {"Authorization": f"Bearer {self.api_key}", "X-Runway-Version": "2024-11-06"}
        body = {"model": self.opts.get("model", "gen4_turbo"), "promptImage": data_uri(refs[0]),
                "promptText": job.prompt[:1000], "ratio": RATIOS.get(job.aspect, "1280:720"),
                "duration": 10 if job.duration > 7 else 5}
        t = await self.http("POST", f"{self.BASE}/image_to_video", h, body)

        async def check():
            s = await self.http("GET", f"{self.BASE}/tasks/{t['id']}", h)
            if s["status"] == "SUCCEEDED":
                return s
            if s["status"] in ("FAILED", "CANCELLED"):
                raise ProviderError(f"runway: {s.get('failure')}", retryable=False)
            if s.get("progress") is not None:
                progress(float(s["progress"]) * 100)
        s = await self.poll(check, progress, est=90)
        await self.download(s["output"][0], dest)
