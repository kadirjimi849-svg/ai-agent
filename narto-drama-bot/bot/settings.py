"""Settings edited from the dashboard (stored in SQLite, override config.yaml).

App credentials (Google / Meta / TikTok / Anthropic keys) are exported to os.environ so the
publishers and tools keep reading them the same way as from .env.
"""
import os

DEFAULTS = {
    "library_root": r"D:\narto-drama",   # one sub-folder per series, episodes inside
    "interval_hours": 8,                 # one new short every N hours
    "clip_seconds": 30,                  # total length of the short (teaser + body + end card)
    "timezone": "Africa/Casablanca",
    "dry_run": False,                    # true = make the video but don't post it
    "domain": "",                        # optional: shown on the video + links in captions
    "drama_url": "",                     # optional: e.g. https://site.com/drama/{slug}
    "clips_per_episode": 3,              # strongest moments taken from one episode before moving on
    "ai_hooks": True,                    # write hooks with Claude when ANTHROPIC_API_KEY is set
    "ai_model": "claude-opus-5",
}

SECRETS = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "META_APP_ID", "META_APP_SECRET",
           "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT", "ANTHROPIC_API_KEY"]


def load(db) -> dict:
    s = {**DEFAULTS, **(db.get("settings") or {})}
    for k in SECRETS:
        if s.get(k):
            os.environ[k] = str(s[k])
    return s


def save(db, patch: dict) -> dict:
    cur = db.get("settings") or {}
    for k, v in patch.items():
        if k not in DEFAULTS and k not in SECRETS:
            continue
        if k in SECRETS and v == "********":  # masked value sent back unchanged
            continue
        if k in DEFAULTS and isinstance(DEFAULTS[k], bool):
            v = v in (True, "true", "1", 1, "on")
        elif k in DEFAULTS and isinstance(DEFAULTS[k], int):
            v = int(float(v))
        cur[k] = v
    cur["interval_hours"] = max(1, cur.get("interval_hours", DEFAULTS["interval_hours"]))
    cur["clip_seconds"] = min(90, max(15, cur.get("clip_seconds", DEFAULTS["clip_seconds"])))
    db.set("settings", cur)
    return load(db)


def public(s: dict) -> dict:
    """Settings for the browser: secrets masked."""
    out = dict(s)
    for k in SECRETS:
        out[k] = "********" if s.get(k) or os.environ.get(k) else ""
    return out


def apply(cfg: dict, s: dict):
    """Push dashboard settings into the runtime config used by Bot/Brain/Copywriter."""
    cfg["timezone"] = s["timezone"]
    cfg["dry_run"] = s["dry_run"]
    cfg["domain"] = s["domain"]
    cfg["drama_url"] = s["drama_url"]
    cfg.setdefault("copywriter", {})
    cfg["copywriter"]["ai"] = bool(s["ai_hooks"])
    cfg["copywriter"]["model"] = s["ai_model"]
    cfg.setdefault("production", {})
    cfg["production"]["clips_per_episode"] = s["clips_per_episode"]
