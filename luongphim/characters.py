import json
from pathlib import Path


class CharacterLibrary:
    """Thư viện nhân vật: tên -> danh sách ảnh tham chiếu (đường dẫn file hoặc URL)."""

    def __init__(self, mapping=None, base_dir="."):
        self.base = Path(base_dir)
        self.map = {}
        for k, v in (mapping or {}).items():
            self.add(k, v if isinstance(v, list) else [v])

    @classmethod
    def load(cls, path):
        p = Path(path)
        return cls(json.loads(p.read_text(encoding="utf-8")), p.parent)

    def add(self, name, refs):
        out = []
        for r in refs:
            if str(r).startswith(("http://", "https://")):
                out.append(str(r))
            else:
                rp = Path(r)
                if not rp.is_absolute():
                    rp = self.base / rp
                if not rp.exists():
                    raise FileNotFoundError(f"ảnh tham chiếu của '{name}' không tồn tại: {rp}")
                out.append(str(rp.resolve()))
        self.map[name] = out

    def refs(self, name):
        if name is None:
            return []
        if name not in self.map:
            raise KeyError(f"không có nhân vật '{name}' trong thư viện")
        return list(self.map[name])

    def names(self):
        return sorted(self.map)
