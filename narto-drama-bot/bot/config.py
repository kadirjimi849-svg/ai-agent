"""Load config.yaml + .env into one object."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Config(dict):
    def __getattr__(self, k):
        v = self.get(k)
        return Config(v) if isinstance(v, dict) else v


def load(path: str | None = None) -> Config:
    _load_env(ROOT / ".env")
    p = Path(path or os.environ.get("BOT_CONFIG", ROOT / "config.yaml"))
    cfg = (yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}) or {}
    cfg.setdefault("paths", {})
    for key, default in [("data", "data"), ("cache", "data/cache"), ("clips", "data/clips")]:
        d = Path(cfg["paths"].get(key, default))
        if not d.is_absolute():
            d = ROOT / d
        d.mkdir(parents=True, exist_ok=True)
        cfg["paths"][key] = str(d)
    cfg.setdefault("timezone", "Africa/Casablanca")
    cfg.setdefault("dry_run", True)
    cfg.setdefault("accounts", [])
    return Config(cfg)


def secret(name: str | None, required=True) -> str | None:
    if not name:
        return None
    v = os.environ.get(name)
    if required and not v:
        raise RuntimeError(f"Missing secret {name} in .env")
    return v
