from pathlib import Path
from uuid import uuid4
from apps.api.app.core.config import settings

class MediaStorage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.media_root).resolve()
    def ensure(self):
        for part in ("assets", "jobs"): (self.root / part).mkdir(parents=True, exist_ok=True)
    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate != self.root and self.root not in candidate.parents: raise ValueError("Caminho de mídia inválido")
        return candidate
    def asset_path(self, extension: str) -> tuple[str, Path]:
        self.ensure(); relative = f"assets/{uuid4()}{extension.lower()}"; return relative, self.resolve(relative)
    def writable(self) -> bool:
        self.ensure(); probe=self.resolve(f".write-{uuid4()}")
        try: probe.write_bytes(b"ok"); return True
        finally: probe.unlink(missing_ok=True)
