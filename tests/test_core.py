import asyncio, json, shutil, subprocess, tempfile, unittest, urllib.request, zipfile, io
from pathlib import Path
from luongphim.engine import Engine
from luongphim.models import Job, ProviderError, RateLimitError, DONE, FAILED
from luongphim.providers import build_providers, MockProvider
from luongphim.providers.base import Provider
from luongphim.characters import CharacterLibrary
from luongphim.batch import load_batch

ROOT = Path(__file__).resolve().parents[1]


async def nosleep(_):
    await asyncio.sleep(0)


class Fake(Provider):
    name = "fake"
    supports_reference = True

    def __init__(self, delay=0.05, fails=None, max_concurrency=2):
        super().__init__(max_concurrency=max_concurrency)
        self.delay, self.fails, self.calls, self.refs_seen = delay, fails or {}, {}, {}

    async def generate(self, job, refs, dest, progress):
        self.calls[job.id] = self.calls.get(job.id, 0) + 1
        self.refs_seen[job.id] = refs
        await asyncio.sleep(self.delay)
        plan = self.fails.get(job.prompt, [])
        n = self.calls[job.id] - 1
        if n < len(plan):
            raise plan[n]
        progress(50)
        Path(dest).write_bytes(b"x")


def run(coro):
    return asyncio.run(coro)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def _go(self, provs, jobs, **kw):
        e = Engine(provs, out_dir=self.tmp, sleep=nosleep, **kw)
        await e.start()
        for j in jobs:
            e.submit(j)
        await asyncio.wait_for(e.join(), 20)
        await e.stop()
        return e

    def test_global_concurrency_limit(self):
        f = Fake(max_concurrency=100)
        e = run(self._go({"fake": f}, [Job(prompt=f"p{i}", provider="fake") for i in range(12)], concurrency=3))
        self.assertEqual(e.peak_running, 3)
        self.assertTrue(all(j.status == DONE for j in e.jobs.values()))

    def test_per_provider_limit(self):
        a, b = Fake(max_concurrency=2), Fake(max_concurrency=1)
        jobs = [Job(prompt=f"a{i}", provider="a") for i in range(6)] + [Job(prompt=f"b{i}", provider="b") for i in range(6)]
        e = run(self._go({"a": a, "b": b}, jobs, concurrency=10))
        self.assertEqual(e.peak_per_provider["a"], 2)
        self.assertEqual(e.peak_per_provider["b"], 1)

    def test_parallel_is_faster(self):
        import time
        f = Fake(delay=0.2, max_concurrency=10)
        t = time.time()
        run(self._go({"fake": f}, [Job(prompt=f"p{i}", provider="fake") for i in range(10)], concurrency=10))
        self.assertLess(time.time() - t, 1.0)

    def test_retry_on_rate_limit_then_success(self):
        f = Fake(fails={"x": [RateLimitError(retry_after=0), RateLimitError()]})
        e = run(self._go({"fake": f}, [Job(prompt="x", provider="fake")], max_retries=3))
        j = list(e.jobs.values())[0]
        self.assertEqual(j.status, DONE)
        self.assertEqual(j.attempts, 3)

    def test_retry_exhausted(self):
        f = Fake(fails={"x": [ProviderError("boom")] * 10})
        e = run(self._go({"fake": f}, [Job(prompt="x", provider="fake")], max_retries=2))
        j = list(e.jobs.values())[0]
        self.assertEqual(j.status, FAILED)
        self.assertEqual(j.attempts, 3)

    def test_non_retryable_fails_fast(self):
        f = Fake(fails={"x": [ProviderError("bad", retryable=False)]})
        e = run(self._go({"fake": f}, [Job(prompt="x", provider="fake")], max_retries=5))
        self.assertEqual(list(e.jobs.values())[0].attempts, 1)

    def test_backoff_exponential_and_capped(self):
        e = Engine({}, out_dir=self.tmp, backoff_base=1, backoff_max=5)
        self.assertLessEqual(e.backoff(1), 1)
        self.assertGreaterEqual(e.backoff(3), 2)
        self.assertEqual(e.backoff(10, None) <= 5, True)
        self.assertEqual(e.backoff(1, retry_after=4), 4)

    def test_manual_retry_failed(self):
        f = Fake(fails={"x": [ProviderError("bad", retryable=False)]})

        async def go():
            e = Engine({"fake": f}, out_dir=self.tmp, sleep=nosleep)
            await e.start()
            e.submit(Job(prompt="x", provider="fake"))
            await e.join()
            self.assertEqual(e.retry_failed().__len__(), 1)
            await e.join()
            await e.stop()
            return e
        e = run(go())
        self.assertEqual(list(e.jobs.values())[0].status, DONE)

    def test_character_refs_passed(self):
        lib = CharacterLibrary.load(ROOT / "examples/characters.json")
        f = Fake()
        e = Engine({"fake": f}, lib, out_dir=self.tmp, sleep=nosleep)

        async def go():
            await e.start()
            e.submit(Job(prompt="a", provider="fake", character="meo_mun"))
            e.submit(Job(prompt="b", provider="fake", character="khong_co"))
            await e.join(); await e.stop()
        run(go())
        js = list(e.jobs.values())
        self.assertTrue(f.refs_seen[js[0].id][0].endswith("meo_mun.png"))
        self.assertEqual(js[1].status, FAILED)

    def test_unknown_provider(self):
        e = run(self._go({}, [Job(prompt="a", provider="nope")]))
        self.assertEqual(list(e.jobs.values())[0].status, FAILED)


class BatchTests(unittest.TestCase):
    def test_json_batch(self):
        jobs, s = load_batch(ROOT / "examples/demo.json")
        self.assertEqual(len(jobs), 24)
        self.assertEqual(s["concurrency"], 8)

    def test_missing_prompt(self):
        with self.assertRaises(ValueError):
            Job.from_spec({"provider": "mock"})

    def test_fallback_to_mock_without_keys(self):
        import os
        for k in ("REPLICATE_API_TOKEN", "FAL_KEY", "RUNWAYML_API_SECRET", "LUMAAI_API_KEY", "GEMINI_API_KEY"):
            os.environ.pop(k, None)
        p, fb = build_providers({"replicate", "veo"})
        self.assertIsInstance(p["replicate"], MockProvider)
        self.assertEqual(sorted(fb), ["replicate", "veo"])
        from luongphim.providers import ReplicateProvider, VeoProvider
        self.assertEqual(p["replicate"].max_concurrency, ReplicateProvider.max_concurrency)
        self.assertEqual(p["veo"].max_concurrency, VeoProvider.max_concurrency)
        p2, _ = build_providers({"fal"}, force_mock=True, config={"fal": {"max_concurrency": 5}})
        self.assertEqual(p2["fal"].max_concurrency, 5)


@unittest.skipUnless(shutil.which("ffmpeg"), "cần ffmpeg")
class MockTests(unittest.TestCase):
    def test_mock_makes_real_mp4_with_ref_and_dashboard(self):
        tmp = tempfile.mkdtemp()
        lib = CharacterLibrary.load(ROOT / "examples/characters.json")
        m = MockProvider(latency=(0.1, 0.2), fail_rate=0, rate_limit_rate=0, seed=1)
        e = Engine({"mock": m}, lib, out_dir=tmp, sleep=nosleep)
        from luongphim.server import serve

        async def go():
            await e.start()
            e.submit(Job(prompt="Mèo Mun chạy", provider="mock", character="meo_mun", duration=2, aspect="9:16"))
            e.submit(Job(prompt="Không nhân vật", provider="mock", duration=1))
            await e.join()
            httpd = serve(e, port=0)
            port = httpd.server_address[1]
            data = await asyncio.to_thread(lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/api/jobs").read())
            z = await asyncio.to_thread(lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/download.zip").read())
            html = await asyncio.to_thread(lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/").read())
            httpd.shutdown(); await e.stop()
            return json.loads(data), z, html.decode()
        d, z, html = run(go())
        self.assertEqual(d["stats"]["done"], 2)
        self.assertIn("Thử lại", html)
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(z)).namelist()), 2)
        for j in e.jobs.values():
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,duration",
                                  "-of", "json", j.output], capture_output=True, text=True).stdout
            st = json.loads(out)["streams"][0]
            self.assertGreater(float(st["duration"]), 0.5)
            self.assertTrue(Path(j.thumb).exists())
        shutil.rmtree(tmp)

    def test_mock_failures_happen(self):
        m = MockProvider(latency=(0.01, 0.02), fail_rate=1.0, rate_limit_rate=0, seed=2)
        with self.assertRaises(ProviderError):
            run(m.generate(Job(prompt="x"), [], Path(tempfile.mktemp(suffix=".mp4")), lambda p: None))


if __name__ == "__main__":
    unittest.main()
