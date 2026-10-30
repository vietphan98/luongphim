import asyncio, io, json, mimetypes, threading, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from .models import DONE

HTML = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")


def make_handler(engine):
    out = engine.out.resolve()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                return self._send(200, HTML, "text/html; charset=utf-8")
            if path == "/api/jobs":
                jobs = [j.to_dict() for j in engine.jobs.values()]
                stats = {s: sum(1 for j in jobs if j["status"] == s) for s in ("queued", "running", "done", "failed")}
                return self._send(200, json.dumps({"jobs": jobs, "stats": stats,
                                                   "concurrency": engine.concurrency,
                                                   "running_now": engine.running_now}, ensure_ascii=False))
            if path.startswith("/files/"):
                f = (out / path[len("/files/"):]).resolve()
                if out not in f.parents or not f.is_file():
                    return self._send(404, '{"error":"không tìm thấy"}')
                return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
            if path == "/download.zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
                    for j in engine.jobs.values():
                        if j.status == DONE and j.output and Path(j.output).exists():
                            z.write(j.output, f"{j.id}_{(j.name or j.provider)}.mp4")
                return self._send(200, buf.getvalue(), "application/zip",
                                  {"Content-Disposition": 'attachment; filename="luongphim_videos.zip"'})
            self._send(404, '{"error":"không tìm thấy"}')

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/api/retry-failed":
                ids = asyncio.run_coroutine_threadsafe(_call(engine.retry_failed), engine.loop).result(5)
                return self._send(200, json.dumps({"retried": ids}))
            if path.startswith("/api/retry/"):
                jid = path.rsplit("/", 1)[1]
                if jid not in engine.jobs:
                    return self._send(404, '{"error":"không có job"}')
                ok = asyncio.run_coroutine_threadsafe(_call(engine.retry, jid), engine.loop).result(5)
                return self._send(200, json.dumps({"ok": ok}))
            self._send(404, '{"error":"không tìm thấy"}')
    return H


async def _call(fn, *a):
    return fn(*a)


def serve(engine, host="127.0.0.1", port=8765):
    httpd = ThreadingHTTPServer((host, port), make_handler(engine))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd
