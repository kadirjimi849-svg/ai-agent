import os
import time

from . import Base, PublishError, cred, req


class Instagram(Base):
    platform = "instagram"

    @property
    def v(self):
        return self.ctx["cfg"].get("graph_version", "v23.0")

    @property
    def token(self):
        return cred(self.acc, "token", "token_env")

    def check(self):
        r = req("GET", f"https://graph.facebook.com/{self.v}/{self.acc['ig_user_id']}",
                params={"fields": "username,followers_count", "access_token": self.token}).json()
        return f"@{r.get('username')} followers={r.get('followers_count')}"

    def publish(self, video_path, cover_path, texts, clip):
        """With a MinIO public URL -> video_url; otherwise the file is uploaded straight from this PC
        (resumable upload to rupload.facebook.com), so no public server is needed."""
        st = self.ctx["storage"]
        base = f"https://graph.facebook.com/{self.v}/{self.acc['ig_user_id']}"
        data = {"media_type": "REELS", "caption": texts["caption"], "share_to_feed": "true", "access_token": self.token}
        if clip["s3_key"]:
            data["video_url"] = st.public_url(clip["s3_key"])
            if clip["cover_s3_key"]:
                data["cover_url"] = st.public_url(clip["cover_s3_key"])
            cid = req("POST", f"{base}/media", data=data).json()["id"]
        else:
            data["upload_type"] = "resumable"
            j = req("POST", f"{base}/media", data=data).json()
            cid = j["id"]
            size = os.path.getsize(video_path)
            with open(video_path, "rb") as f:
                req("POST", j.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{self.v}/{cid}",
                    headers={"Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(size)},
                    data=f.read(), timeout=900)
        for _ in range(60):
            s = req("GET", f"https://graph.facebook.com/{self.v}/{cid}",
                    params={"fields": "status_code,status", "access_token": self.token}).json()
            if s.get("status_code") == "FINISHED":
                break
            if s.get("status_code") in ("ERROR", "EXPIRED"):
                raise PublishError(f"IG container {s}")
            time.sleep(10)
        else:
            raise PublishError("IG container timeout")
        mid = req("POST", f"{base}/media_publish", data={"creation_id": cid, "access_token": self.token}).json()["id"]
        link = req("GET", f"https://graph.facebook.com/{self.v}/{mid}",
                   params={"fields": "permalink", "access_token": self.token}).json().get("permalink")
        return {"id": mid, "url": link, "meta": {}}

    def stats(self, external_id, meta):
        try:
            j = req("GET", f"https://graph.facebook.com/{self.v}/{external_id}/insights",
                    params={"metric": "views,likes,comments,shares", "access_token": self.token}).json()
            return {m["name"]: int((m.get("values") or [{}])[0].get("value", 0)) for m in j.get("data", [])}
        except PublishError as e:
            print(f"[instagram] stats: {e}")
            return {}
