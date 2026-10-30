import shutil, subprocess
from pathlib import Path

FONT_CANDIDATES = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                   "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                   "/Library/Fonts/Arial Unicode.ttf", "C:/Windows/Fonts/arial.ttf"]


def ffmpeg_bin():
    b = shutil.which("ffmpeg")
    if not b:
        raise RuntimeError("cần cài ffmpeg")
    return b


def font():
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def run(args):
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg lỗi: " + r.stderr[-400:])


def thumbnail(video, out):
    run(["-ss", "0.8", "-i", str(video), "-frames:v", "1", "-vf", "scale=320:-2", str(out)])
