import asyncio, colorsys, random, tempfile, os
from pathlib import Path
from .base import Provider, ASPECTS
from ..models import ProviderError, RateLimitError
from .. import media


class MockProvider(Provider):
    """Provider giả lập: tạo MP4 thật bằng ffmpeg, có độ trễ và lỗi ngẫu nhiên."""
    name = "mock"
    supports_reference = True
    max_concurrency = 6

    def __init__(self, latency=(4.0, 9.0), fail_rate=0.15, rate_limit_rate=0.05, seed=None, **kw):
        super().__init__(**kw)
        self.latency = latency
        self.fail_rate = fail_rate
        self.rate_limit_rate = rate_limit_rate
        self.rng = random.Random(seed)

    async def generate(self, job, refs, dest, progress):
        total = self.rng.uniform(*self.latency)
        steps = 20
        fail_at = self.rng.randint(5, 17) if self.rng.random() < self.fail_rate else None
        if self.rng.random() < self.rate_limit_rate:
            await asyncio.sleep(0.3)
            raise RateLimitError("mock: 429 Too Many Requests (giả lập)", retry_after=1.0)
        for i in range(steps):
            await asyncio.sleep(total / steps)
            progress(100.0 * (i + 1) / (steps + 1))
            if fail_at == i:
                raise ProviderError("mock: lỗi ngẫu nhiên giả lập (GPU hết bộ nhớ)", retryable=False)
        await asyncio.to_thread(render_clip, job, refs, dest)


def render_clip(job, refs, dest):
    w, h = ASPECTS.get(job.aspect, (1280, 720))
    w, h = w // 2, h // 2  # nhẹ cho demo
    dur = max(1.0, min(float(job.duration), 10.0))
    hue = (sum(map(ord, job.prompt)) % 360) / 360
    r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.6, 0.55))
    color = f"0x{r:02x}{g:02x}{b:02x}"
    font = media.font()
    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    words, lines, cur = job.prompt.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) > 26:
            lines.append(cur); cur = wd
        else:
            cur = (cur + " " + wd).strip()
    lines.append(cur)
    tmp.write("\n".join(lines[:5])); tmp.close()
    fs = max(14, w // 24)
    ff = f":fontfile='{font}'" if font else ""
    txt = (f"drawtext=textfile='{tmp.name}'{ff}:fontsize={fs}:fontcolor=white:line_spacing=6:"
           f"x=(w-text_w)/2:y=h*0.62+10*sin(t*2):box=1:boxcolor=black@0.45:boxborderw=8")
    lbl = (f",drawtext=text='{job.id}  %{{eif\\:t\\:d}}s'{ff}:fontsize={fs}:fontcolor=yellow:x=12:y=12")
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={dur}:r=24"]
    if refs and Path(refs[0]).exists():
        size = min(w, h) // 3
        args += ["-loop", "1", "-i", refs[0]]
        flt = (f"[1:v]scale={size}:{size}:force_original_aspect_ratio=decrease[ref];"
               f"[0:v][ref]overlay=x=(W-w)/2+(W/4)*sin(t*1.5):y=H*0.12[bg];[bg]{txt}{lbl}[v]")
    else:
        flt = f"[0:v]{txt}{lbl}[v]"
    try:
        media.run([*args, "-filter_complex", flt, "-map", "[v]", "-t", str(dur),
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", str(dest)])
    finally:
        os.unlink(tmp.name)
