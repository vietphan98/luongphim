from .base import Provider, data_uri
from ..models import ProviderError


class ReplicateProvider(Provider):
    """Replicate HTTP API: POST /v1/models/{owner}/{name}/predictions, poll urls.get.
    Mặc định model minimax/video-01 (có first_frame_image). Đổi qua opts model=..."""
    name = "replicate"
    env_key = "REPLICATE_API_TOKEN"
    supports_reference = True
    max_concurrency = 3

    async def generate(self, job, refs, dest, progress):
        model = self.opts.get("model", "minimax/video-01")
        h = {"Authorization": f"Bearer {self.api_key}", "Prefer": "wait=1"}
        inp = {"prompt": job.prompt, **self.opts.get("extra_input", {})}
        if refs:
            inp[self.opts.get("image_field", "first_frame_image")] = data_uri(refs[0])
        pred = await self.http("POST", f"https://api.replicate.com/v1/models/{model}/predictions",
                               h, {"input": inp})
        url = pred["urls"]["get"]

        async def check():
            p = await self.http("GET", url, {"Authorization": f"Bearer {self.api_key}"})
            if p["status"] == "succeeded":
                return p
            if p["status"] in ("failed", "canceled"):
                raise ProviderError(f"replicate: {p.get('error')}", retryable=False)
        p = await self.poll(check, progress, est=180)
        out = p["output"]
        out = out[0] if isinstance(out, list) else out
        await self.download(out, dest)
