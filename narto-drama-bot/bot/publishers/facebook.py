import os
import time

from . import Base, PublishError, cred, req


class Facebook(Base):
    platform = "facebook"

    @property
    def v(self):
        return self.ctx["cfg"].get("graph_version", "v23.0")

    @property
    def token(self):
        return cred(self.acc, "token", "token_env")

    def check(self):
        r = req("GET", f"https://graph.facebook.com/{self.v}/{self.acc['page_id']}",
                params={"fields": "name,followers_count", "access_token": self.token}).json()
        return f"page '{r.get('name')}' followers={r.get('followers_count')}"

    def publish(self, video_path, cover_path, texts, clip):
        page, tok, v = self.acc["page_id"], self.token, self.v
        start = req("POST", f"https://graph.facebook.com/{v}/{page}/video_reels",
                    data={"upload_phase": "start", "access_token": tok}).json()
        vid = start["video_id"]
        size = os.path.getsize(video_path)
        with open(video_path, "rb") as f:
            req("POST", start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{v}/{vid}",
                headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)},
                data=f.read(), timeout=900)
        req("POST", f"https://graph.facebook.com/{v}/{page}/video_reels",
            data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                  "description": texts["caption"], "access_token": tok})
        # wait for processing (non-fatal if slow)
        for _ in range(40):
            st = req("GET", f"https://graph.facebook.com/{v}/{vid}", params={"fields": "status", "access_token": tok}).json()
            s = st.get("status", {})
            if s.get("video_status") == "ready" or s.get("publishing_phase", {}).get("status") == "complete":
                break
            if s.get("video_status") == "error":
                raise PublishError(f"FB processing error: {s}")
            time.sleep(15)
        if self.acc.get("first_comment", True) and texts.get("link"):
            try:  # clickable link as first comment
                req("POST", f"https://graph.facebook.com/{v}/{vid}/comments",
                    data={"message": f"🎬 الحلقات كاملة هنا 👉 {texts['link']}", "access_token": tok})
            except PublishError as e:
                print(f"[facebook] first comment failed: {e}")
        return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}", "meta": {}}

    def stats(self, external_id, meta):
        tok, v = self.token, self.v
        out = {}
        try:
            j = req("GET", f"https://graph.facebook.com/{v}/{external_id}/video_insights",
                    params={"metric": "blue_reels_play_count,post_video_likes_by_reaction_type,post_video_social_actions",
                            "access_token": tok}).json()
            for m in j.get("data", []):
                val = (m.get("values") or [{}])[0].get("value")
                if m["name"] == "blue_reels_play_count":
                    out["views"] = int(val or 0)
                elif m["name"] == "post_video_likes_by_reaction_type" and isinstance(val, dict):
                    out["likes"] = sum(val.values())
                elif m["name"] == "post_video_social_actions" and isinstance(val, dict):
                    out["comments"] = int(val.get("COMMENT", 0))
                    out["shares"] = int(val.get("SHARE", 0))
        except PublishError as e:
            print(f"[facebook] stats: {e}")
        return out
