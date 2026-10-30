from __future__ import annotations
import asyncio, logging, random, time
from pathlib import Path
from .models import Job, QUEUED, RUNNING, DONE, FAILED, ProviderError, RateLimitError
from . import media

log = logging.getLogger("luongphim")


class Engine:
    """Hàng đợi job với giới hạn đồng thời toàn cục + theo từng provider, có retry/backoff."""

    def __init__(self, providers: dict, characters=None, out_dir="output", concurrency=4,
                 max_retries=3, backoff_base=1.0, backoff_max=30.0, sleep=asyncio.sleep):
        self.providers = providers
        self.characters = characters
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.concurrency = concurrency
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self._sleep = sleep
        self.jobs: dict[str, Job] = {}
        self._queue: asyncio.Queue | None = None
        self._psem: dict[str, asyncio.Semaphore] = {}
        self._workers = []
        self.loop = None
        self.running_now = 0
        self.peak_running = 0
        self.peak_per_provider: dict[str, int] = {}
        self._per_provider_now: dict[str, int] = {}

    def _sem(self, name):
        if name not in self._psem:
            self._psem[name] = asyncio.Semaphore(max(1, int(getattr(self.providers[name], "max_concurrency", 2))))
        return self._psem[name]

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self.concurrency)]

    def submit(self, job: Job):
        if job.provider not in self.providers:
            job.status, job.error = FAILED, f"provider không tồn tại: {job.provider}"
            self.jobs[job.id] = job
            return job
        self.jobs[job.id] = job
        job.status, job.progress, job.error = QUEUED, 0.0, None
        self._queue.put_nowait(job.id)
        return job

    def retry(self, job_id):
        job = self.jobs[job_id]
        if job.status != FAILED:
            return False
        job.attempts = 0
        self.submit(job)
        return True

    def retry_failed(self):
        return [j.id for j in list(self.jobs.values()) if j.status == FAILED and self.retry(j.id)]

    async def join(self):
        await self._queue.join()

    async def stop(self):
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    def backoff(self, attempt, retry_after=None):
        if retry_after is not None:
            return min(self.backoff_max, float(retry_after))
        d = self.backoff_base * (2 ** (attempt - 1))
        return min(self.backoff_max, d * (0.5 + random.random() / 2))

    async def _worker(self, idx):
        while True:
            jid = await self._queue.get()
            try:
                await self._run(self.jobs[jid])
            except Exception as e:  # không để worker chết
                log.exception("lỗi không mong đợi")
                self.jobs[jid].status, self.jobs[jid].error = FAILED, repr(e)
            finally:
                self._queue.task_done()

    async def _run(self, job: Job):
        prov = self.providers[job.provider]
        job.effective_provider = prov.name
        try:
            refs = self.characters.refs(job.character) if (self.characters and job.character) else []
        except KeyError as e:
            job.status, job.error = FAILED, str(e)
            return
        if refs and not prov.supports_reference:
            job.note = f"{prov.name} không nhận ảnh tham chiếu; bỏ qua ảnh nhân vật"
            refs = []
        sem = self._sem(job.provider)
        while True:
            job.attempts += 1
            async with sem:
                self.running_now += 1
                pn = self._per_provider_now.get(job.provider, 0) + 1
                self._per_provider_now[job.provider] = pn
                self.peak_running = max(self.peak_running, self.running_now)
                self.peak_per_provider[job.provider] = max(self.peak_per_provider.get(job.provider, 0), pn)
                job.status, job.progress, job.error = RUNNING, 0.0, None
                job.started = job.started or time.time()
                try:
                    dest = self.out / f"{job.id}.mp4"

                    def cb(p, job=job):
                        job.progress = max(0.0, min(99.0, float(p)))
                    await prov.generate(job, refs, dest, cb)
                    job.output = str(dest)
                    job.progress, job.status, job.finished = 100.0, DONE, time.time()
                    try:
                        thumb = self.out / f"{job.id}.jpg"
                        await asyncio.to_thread(media.thumbnail, dest, thumb)
                        job.thumb = str(thumb)
                    except Exception as e:
                        log.warning("không tạo được thumbnail cho %s: %s", job.id, e)
                    return
                except ProviderError as e:
                    err = e
                except Exception as e:
                    err = ProviderError(repr(e), retryable=True)
                finally:
                    self.running_now -= 1
                    self._per_provider_now[job.provider] -= 1
            job.error = str(err)
            if not err.retryable or job.attempts > self.max_retries:
                job.status, job.finished = FAILED, time.time()
                return
            job.status, job.progress = QUEUED, 0.0
            await self._sleep(self.backoff(job.attempts, getattr(err, "retry_after", None)))
