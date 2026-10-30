import argparse, asyncio, json, logging, os, sys, webbrowser
from pathlib import Path
from .batch import load_batch
from .characters import CharacterLibrary
from .engine import Engine
from .providers import build_providers
from .server import serve


def main(argv=None):
    ap = argparse.ArgumentParser(prog="luongphim", description="Chạy nhiều job tạo video AI song song")
    ap.add_argument("batch", help="file batch .json/.yaml")
    ap.add_argument("-c", "--concurrency", type=int, help="số job chạy đồng thời tối đa (mặc định 6)")
    ap.add_argument("--characters", help="file thư viện nhân vật (json)")
    ap.add_argument("-o", "--out", default="output", help="thư mục kết quả")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mock", action="store_true", help="ép mọi provider dùng mock")
    ap.add_argument("--retries", type=int, help="số lần thử lại tối đa (mặc định 3)")
    ap.add_argument("--fail-rate", type=float, help="tỉ lệ lỗi giả lập của mock")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--exit-when-done", action="store_true", help="thoát khi xong hết (không giữ dashboard)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    jobs, settings = load_batch(a.batch)
    chars_file = a.characters or settings.get("characters")
    chars = None
    if chars_file:
        cp = Path(chars_file)
        if not cp.is_absolute():
            cp = Path(a.batch).parent / cp
        chars = CharacterLibrary.load(cp)
    mock_opts = {}
    if a.fail_rate is not None:
        mock_opts["fail_rate"] = a.fail_rate
    provs, fb = build_providers({j.provider for j in jobs}, a.mock, settings.get("providers", {}), mock_opts)
    if fb:
        print(f"⚠ Thiếu API key -> dùng mock thay cho: {', '.join(sorted(fb))}")
    asyncio.run(_run(a, jobs, settings, provs, chars))


async def _run(a, jobs, settings, provs, chars):
    eng = Engine(provs, chars, a.out, concurrency=a.concurrency or settings.get("concurrency", 6),
                 max_retries=a.retries if a.retries is not None else settings.get("max_retries", 3))
    await eng.start()
    httpd = serve(eng, a.host, a.port)
    url = f"http://{a.host}:{a.port}/"
    print(f"Dashboard: {url}  ({len(jobs)} job, đồng thời {eng.concurrency})")
    if not a.no_browser:
        try: webbrowser.open(url)
        except Exception: pass
    for j in jobs:
        eng.submit(j)
    await eng.join()
    st = {}
    for j in eng.jobs.values():
        st[j.status] = st.get(j.status, 0) + 1
    print("Kết quả:", json.dumps(st, ensure_ascii=False), "| peak đồng thời:", eng.peak_running)
    if a.exit_when_done:
        httpd.shutdown(); await eng.stop(); return
    print("Dashboard vẫn chạy (retry/tải zip). Ctrl+C để thoát.")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    main()
