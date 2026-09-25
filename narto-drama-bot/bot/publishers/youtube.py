import os
import time

from ..config import secret
from . import Base, PublishError, cred, req

TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTube(Base):
    platform = "youtube"

    def _token(self):
        db = self.ctx["db"]
        key = f"yt_token:{self.acc['name']}"
        cached = db.get(key)
        if cached and cached["exp"] > time.time() + 120:
            return cached["access_token"]
        j = req("POST", TOKEN_URL, data={
            "client_id": secret(self.acc.get("client_id_env", "YT_CLIENT_ID")),
            "client_secret": secret(self.acc.get("client_secret_env", "YT_CLIENT_SECRET")),
            "refresh_token": cred(self.acc, "refresh_token", "refresh_token_env"), "grant_type": "refresh_token"}).json()
        db.set(key, {"access_token": j["access_token"], "exp": time.time() + j.get("expires_in", 3600)})
        return j["access_token"]

    def check(self):
        j = req("GET", "https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet,statistics", "mine": "true"},
                headers={"Authorization": f"Bearer {self._token()}"}).json()
        it = (j.get("items") or [{}])[0]
        return f"channel '{it.get('snippet', {}).get('title')}' subs={it.get('statistics', {}).get('subscriberCount')}"

    def publish(self, video_path, cover_path, texts, clip):
        tok = self._token()
        size = os.path.getsize(video_path)
        body = {"snippet": {"title": texts["title"], "description": texts["caption"],
                            "tags": [t.strip("#") for t in texts["caption"].split() if t.startswith("#")][:15],
                            "categoryId": "24", "defaultLanguage": self.acc.get("lang", "ar")},
                "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
        init = req("POST", "https://www.googleapis.com/upload/youtube/v3/videos",
                   params={"uploadType": "resumable", "part": "snippet,status"},
                   headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                            "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                   json=body)
        loc = init.headers["Location"]
        with open(video_path, "rb") as f:
            j = req("PUT", loc, headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4"},
                    data=f.read(), timeout=1800).json()
        vid = j.get("id")
        if not vid:
            raise PublishError(f"YouTube upload: {j}")
        return {"id": vid, "url": f"https://youtube.com/shorts/{vid}", "meta": {}}

    def stats(self, external_id, meta):
        j = req("GET", "https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics", "id": external_id},
                headers={"Authorization": f"Bearer {self._token()}"}).json()
        s = (j.get("items") or [{}])[0].get("statistics", {})
        return {"views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0))}
