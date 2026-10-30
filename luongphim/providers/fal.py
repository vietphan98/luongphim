from .base import Provider, data_uri
from ..models import ProviderError


class FalProvider(Provider):
    """fal.ai Queue API: POST https://queue.fal.run/{model}, poll status_url, lấy response_url."""
    name = "fal"
    env_key = "FAL_KEY"
    supports_reference = True
    max_concurrency = 3

    async def generate(self, job, refs, dest, progress):
        h = {"Authorization": f"Key {self.api_key}"}
        if refs:
            model = self.opts.get("i2v_model", "fal-ai/kling-video/v1.6/standard/image-to-video")
        else:
            model = self.opts.get("t2v_model", "fal-ai/kling-video/v1.6/standard/text-to-video")
        body = {"prompt": job.prompt, "duration": "10" if job.duration > 7 else "5",
                "aspect_ratio": job.aspect}
        if refs:
            body["image_url"] = data_uri(refs[0])
        sub = await self.http("POST", f"https://queue.fal.run/{model}", h, body)

        async def check():
            s = await self.http("GET", sub["status_url"], h)
            if s.get("status") == "COMPLETED":
                return s
            if s.get("status") not in ("IN_QUEUE", "IN_PROGRESS"):
                raise ProviderError(f"fal: trạng thái lạ {s}", retryable=False)
        await self.poll(check, progress, est=150)
        res = await self.http("GET", sub["response_url"], h)
        if "video" not in res:
            raise ProviderError(f"fal: không có video trong kết quả: {str(res)[:200]}", retryable=False)
        await self.download(res["video"]["url"], dest)
