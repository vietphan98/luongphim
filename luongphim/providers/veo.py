from .base import Provider, b64
from ..models import ProviderError


class VeoProvider(Provider):
    """Google Veo qua Gemini API: POST models/{model}:predictLongRunning, poll operation."""
    name = "veo"
    env_key = "GEMINI_API_KEY"
    supports_reference = True
    max_concurrency = 2
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    async def generate(self, job, refs, dest, progress):
        model = self.opts.get("model", "veo-3.0-generate-001")
        h = {"x-goog-api-key": self.api_key}
        inst = {"prompt": job.prompt}
        if refs and not refs[0].startswith("http"):
            data, mime = b64(refs[0])
            inst["image"] = {"bytesBase64Encoded": data, "mimeType": mime}
        params = {"aspectRatio": job.aspect if job.aspect in ("16:9", "9:16") else "16:9"}
        if self.opts.get("send_duration"):
            params["durationSeconds"] = int(job.duration)
        op = await self.http("POST", f"{self.BASE}/models/{model}:predictLongRunning", h,
                             {"instances": [inst], "parameters": params})

        async def check():
            s = await self.http("GET", f"{self.BASE}/{op['name']}", h)
            if s.get("done"):
                if "error" in s:
                    raise ProviderError(f"veo: {s['error']}", retryable=False)
                return s
        s = await self.poll(check, progress, est=90)
        try:
            uri = s["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"]
        except (KeyError, IndexError):
            raise ProviderError(f"veo: không có video (có thể bị lọc an toàn): {str(s)[:200]}", retryable=False)
        await self.download(uri, dest, headers=h)
