"""Publishers use only official APIs:
  facebook  -> Graph API  /{page}/video_reels   (Reels)
  instagram -> Graph API  /{ig-user}/media REELS (needs a public video URL -> MinIO)
  youtube   -> YouTube Data API v3 resumable upload (#shorts)
  tiktok    -> TikTok Content Posting API (direct post)
"""
import time

import requests


class PublishError(Exception):
    pass


def req(method, url, retries=3, **kw):
    kw.setdefault("timeout", 120)
    for i in range(retries):
        try:
            r = requests.request(method, url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(5 * (i + 1) ** 2)
                continue
            if r.status_code >= 400:
                raise PublishError(f"{method} {url.split('?')[0]} -> {r.status_code}: {r.text[:800]}")
            return r
        except requests.RequestException as e:
            if i == retries - 1:
                raise PublishError(str(e))
            time.sleep(5 * (i + 1))


def cred(acc, key, env_field, default_env=None):
    """Token stored on the account (connected from the dashboard) or named env var (config.yaml + .env)."""
    if acc.get(key):
        return acc[key]
    from ..config import secret
    return secret(acc.get(env_field) or default_env)


def get_publisher(platform, account, ctx):
    from . import facebook, instagram, tiktok, youtube
    cls = {"facebook": facebook.Facebook, "instagram": instagram.Instagram,
           "youtube": youtube.YouTube, "tiktok": tiktok.TikTok}[platform]
    return cls(account, ctx)


class Base:
    platform = ""

    def __init__(self, account, ctx):
        self.acc = account      # dict from config.accounts
        self.ctx = ctx          # {"db":..., "storage":..., "cfg":...}

    def publish(self, video_path, cover_path, texts, clip) -> dict:
        """-> {"id": ..., "url": ..., "meta": {...}}"""
        raise NotImplementedError

    def stats(self, external_id, meta) -> dict:
        """-> {"views":..,"likes":..,"comments":..,"shares":..}"""
        return {}

    def check(self) -> str:
        return "ok"
