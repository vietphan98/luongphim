import json
from pathlib import Path
from .models import Job


def load_batch(path):
    """Đọc file batch JSON hoặc YAML (YAML cần PyYAML)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise SystemExit("File YAML cần PyYAML: pip install pyyaml (hoặc dùng JSON)") from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if isinstance(data, list):
        data = {"jobs": data}
    defaults = data.get("defaults", {})
    jobs = []
    for spec in data.get("jobs", []):
        n = int(spec.pop("repeat", 1)) if isinstance(spec, dict) else 1
        for i in range(n):
            s = dict(spec)
            if n > 1 and s.get("name"):
                s["name"] = f"{s['name']}-{i+1}"
            jobs.append(Job.from_spec(s, defaults))
    return jobs, data.get("settings", {})
