import math
import os
import time

from ..config import secret
from . import Base, PublishError, cred, req

API = "https://open.tiktokapis.com/v2"
MB = 1024 * 1024


class TikTok(Base):
    platform = "tiktok"

    def _token(self):
        """Access tokens live 24h; refresh tokens rotate -> keep the newest in the DB."""
        db = self.ctx["db"]
        key = f"tt_token:{self.acc['name']}"
        t = db.get(key) or {}
        if t.get("access_token") and t.get("exp", 0) > time.time() + 300:
            return t["access_token"]
        refresh = t.get("refresh_token") or cred(self.acc, "refresh_token", "refresh_token_env")
        j = req("POST", f"{API}/oauth/token/", data={
            "client_key": secret(self.acc.get("client_key_env", "TIKTOK_CLIENT_KEY")),
            "client_secret": secret(self.acc.get("client_secret_env", "TIKTOK_CLIENT_SECRET")),
            "grant_type": "refresh_token", "refresh_token": refresh},
            headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" not in j:
            raise PublishError(f"TikTok token refresh failed: {j}")
        db.set(key, {"access_token": j["access_token"], "refresh_token": j.get("refresh_token", refresh),
                     "exp": time.time() + int(j.get("expires_in", 86400))})
        return j["access_token"]

    def _h(self):
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json; charset=UTF-8"}

    def check(self):
        j = req("POST", f"{API}/post/publish/creator_info/query/", headers=self._h()).json()
        d = j.get("data", {})
        return f"@{d.get('creator_username')} privacy_options={d.get('privacy_level_options')}"

    def publish(self, video_path, cover_path, texts, clip):
        info = req("POST", f"{API}/post/publish/creator_info/query/", headers=self._h()).json().get("data", {})
        opts = info.get("privacy_level_options") or ["SELF_ONLY"]
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in opts else opts[0]
        size = os.path.getsize(video_path)
        if size <= 64 * MB:
            chunk, count = size, 1
        else:
            chunk = 10 * MB
            count = size // chunk  # last chunk absorbs the remainder (API rule)
        j = req("POST", f"{API}/post/publish/video/init/", headers=self._h(), json={
            "post_info": {"title": texts["caption"][:2200], "privacy_level": privacy,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                          "video_cover_timestamp_ms": 1000},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
                            "total_chunk_count": count}}).json()
        data = j.get("data") or {}
        if not data.get("upload_url"):
            raise PublishError(f"TikTok init: {j}")
        with open(video_path, "rb") as f:
            for i in range(count):
                start = i * chunk
                end = size - 1 if i == count - 1 else start + chunk - 1
                f.seek(start)
                req("PUT", data["upload_url"], data=f.read(end - start + 1), timeout=900, headers={
                    "Content-Type": "video/mp4", "Content-Range": f"bytes {start}-{end}/{size}"})
        pid = data["publish_id"]
        post_id = None
        for _ in range(40):
            s = req("POST", f"{API}/post/publish/status/fetch/", headers=self._h(), json={"publish_id": pid}).json().get("data", {})
            if s.get("status") == "PUBLISH_COMPLETE":
                ids = s.get("publicaly_available_post_id") or []
                post_id = str(ids[0]) if ids else None
                break
            if s.get("status") == "FAILED":
                raise PublishError(f"TikTok publish failed: {s.get('fail_reason')}")
            time.sleep(10)
        url = f"https://www.tiktok.com/@{info.get('creator_username')}/video/{post_id}" if post_id else None
        return {"id": post_id or pid, "url": url, "meta": {"publish_id": pid, "privacy": privacy}}

    def stats(self, external_id, meta):
        if not external_id or not external_id.isdigit():
            return {}
        j = req("POST", f"{API}/video/query/", params={"fields": "id,view_count,like_count,comment_count,share_count"},
                headers=self._h(), json={"filters": {"video_ids": [external_id]}}).json()
        v = ((j.get("data") or {}).get("videos") or [{}])[0]
        return {"views": v.get("view_count", 0), "likes": v.get("like_count", 0),
                "comments": v.get("comment_count", 0), "shares": v.get("share_count", 0)}
