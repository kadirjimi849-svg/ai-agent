"""Autopilot: every N hours (default 8)

  1. rescan the series folder (new series / episodes are picked up automatically)
  2. choose a series (rotation + what performs best) and its next unused episode
  3. find the strongest moment -> 30s vertical short: 2s flash-forward + hook text, body that ends
     on the cliffhanger, end card
  4. post the same short to every connected account (YouTube, Facebook, Instagram, TikTok)
  5. every 6h pull views/likes back so the next choices favour what works
"""
import json
import random
import threading
import time
import traceback
from pathlib import Path

from . import accounts, analyzer, editor, library, settings
from .logs import log

TEASER = 2.2


class Autopilot:
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self.yaml_accounts = [a for a in bot.cfg.get("accounts", []) if a.get("enabled", True)]
        self.lock = threading.Lock()
        self.status = {"busy": False, "step": "", "last_error": ""}
        self._thread = None
        self.reload()

    # ------------------------------------------------------------------ state
    def reload(self):
        self.s = settings.load(self.db)
        settings.apply(self.bot.cfg, self.s)
        self.bot.cfg["accounts"] = self.yaml_accounts + accounts.all_accounts(self.db)
        return self.s

    @property
    def state(self):
        return self.db.get("autopilot") or {"enabled": False, "last_run": None, "next_run": None}

    def _save_state(self, **kw):
        st = self.state
        st.update(kw)
        self.db.set("autopilot", st)
        return st

    def enable(self, on: bool):
        st = self.state
        nxt = st.get("next_run")
        if on and (not nxt or nxt < time.time()):
            nxt = time.time() + 5
        return self._save_state(enabled=on, next_run=nxt)

    def targets(self):
        return [a for a in self.bot.cfg["accounts"] if a.get("enabled", True)]

    def _step(self, text):
        self.status["step"] = text
        log(text)

    # ------------------------------------------------------------------ production
    def _pick(self, tried):
        per_ep = int(self.s.get("clips_per_episode", 3))
        slugs = [r["slug"] for r in self.db.q("SELECT slug FROM dramas WHERE active=1") if r["slug"] not in tried]
        slugs = [s for s in slugs if self.bot._next_episode(s, per_ep)]
        if not slugs:
            return None, None
        recent = [r["drama_slug"] for r in self.db.q(
            "SELECT e.drama_slug FROM clips c JOIN episodes e ON e.id=c.episode_id ORDER BY c.id DESC LIMIT 30")]
        recent = list(dict.fromkeys(recent))[: max(0, min(len(slugs) - 1, len(slugs) // 2, 10))]
        fresh = [s for s in slugs if s not in recent] or slugs
        random.shuffle(fresh)  # ties (series with no stats yet) are rotated randomly
        slug = self.bot.brain.pick_drama(fresh)
        return slug, self.bot._next_episode(slug, per_ep)

    def make_short(self, drama_slug=None):
        """Renders one short. Returns the clip id, or None when the library has nothing left."""
        tried = set()
        cfg = self.bot.cfg
        body = float(self.s["clip_seconds"]) - TEASER - editor.END_CARD
        for _ in range(6):
            if drama_slug:
                slug, ep = drama_slug, self.bot._next_episode(drama_slug, int(self.s.get("clips_per_episode", 3)))
                drama_slug = None
            else:
                slug, ep = self._pick(tried)
            if not ep:
                if slug:
                    tried.add(slug)
                    continue
                return None
            drama = self.db.one("SELECT * FROM dramas WHERE slug=?", slug)
            self._step(f"تحليل: {drama['title']} – الحلقة {ep['ep_no']}")
            if not Path(ep["src"]).exists() and not ep["src"].startswith("s3://"):
                log(f"  file missing, skipping: {ep['src']}")
                self.db.x("DELETE FROM episodes WHERE id=?", ep["id"])
                continue
            src = self.bot.storage.fetch(ep["src"], cfg["paths"]["cache"])
            a = json.loads(ep["analysis"]) if ep["analysis"] else None
            if not a:
                try:
                    a = analyzer.analyze(src)
                except Exception as e:
                    log(f"  analyze failed ({e}); skipping episode")
                    a = {"exhausted": 1}
                    self.db.x("UPDATE episodes SET analysis=? WHERE id=?", json.dumps(a), ep["id"])
                    continue
                self.db.x("UPDATE episodes SET analysis=? WHERE id=?", json.dumps(a), ep["id"])
            taken = [(r["start"], r["end"]) for r in self.db.q("SELECT DISTINCT start,end FROM clips WHERE episode_id=?", ep["id"])]
            plans = analyzer.plan_clips(a, count=1, min_len=body, max_len=body, taken=taken, teaser_len=TEASER)
            if not plans:
                a["exhausted"] = 1
                self.db.x("UPDATE episodes SET analysis=? WHERE id=?", json.dumps(a), ep["id"])
                continue
            plan = plans[0]  # strongest remaining moment of this episode
            recent_hooks = {r["hook_text"] for r in self.db.q("SELECT hook_text FROM clips ORDER BY id DESC LIMIT 20")}
            style, hook = self.bot.copy.best_hook(drama, "ar", recent_hooks)
            label = f"{drama['title']} • الحلقة {ep['ep_no']}"
            name = f"{slug}_e{ep['ep_no']:03d}_{int(plan['start'])}_{int(time.time())}"
            out = Path(cfg["paths"]["clips"]) / f"{name}.mp4"
            vertical = bool(a.get("height") and a.get("width") and a["height"] / a["width"] > 1.5)
            self._step(f"مونتاج {self.s['clip_seconds']} ثانية: «{hook}»")
            try:
                path, cover, _ = editor.render(
                    src, plan, out, hook_text=hook, label=label, domain=self.bot.domain,
                    end_lines=(*self.bot.copy.end_lines("ar", bool(self.bot.domain)), drama["title"]),
                    font_path=self.bot.font, has_audio=a.get("has_audio", True), vertical=vertical,
                    accent=self.bot.accent, preset=(cfg.get("render") or {}).get("preset", "veryfast"))
            except Exception as e:
                log(f"  render failed: {e}")
                tried.add(slug)
                continue
            s3_key = cover_key = None
            if (cfg.get("minio") or {}).get("clips_bucket"):
                try:
                    s3_key = self.bot.storage.upload(path, f"shorts/{name}.mp4")
                    cover_key = self.bot.storage.upload(cover, f"shorts/{name}.jpg", "image/jpeg")
                except Exception as e:
                    log(f"  minio upload failed: {e}")
            cid = self.db.x("""INSERT INTO clips(episode_id,variant,lang,hook_id,hook_text,start,end,teaser_start,
                               teaser_end,score,path,cover,s3_key,cover_s3_key,status,created_at)
                               VALUES(?,0,'ar',?,?,?,?,?,?,?,?,?,?,?,'ready',?)""",
                            ep["id"], style, hook, plan["start"], plan["end"], plan["teaser_start"], plan["teaser_end"],
                            plan["score"], path, cover, s3_key, cover_key, time.time())
            log(f"  clip #{cid} ready: {Path(path).name}")
            return cid
        return None

    def publish_all(self, clip_id):
        results = []
        dry = bool(self.s.get("dry_run"))
        for acc in self.targets():
            self._step(f"نشر على {acc['platform']} ({acc.get('label') or acc['name']})")
            res = self.bot.publish_next(acc, clip_id, dry=dry)
            results.append({"account": acc["name"], "platform": acc["platform"], "ok": bool(res)})
        self.db.x("UPDATE clips SET status='posted' WHERE id=?", clip_id)
        return results

    def cycle(self, drama_slug=None, publish=True):
        """One full run: scan -> render -> post. Safe to call from the dashboard ("run now")."""
        if not self.lock.acquire(blocking=False):
            return {"error": "busy"}
        started = time.time()
        self.status.update(busy=True, last_error="")
        try:
            self.reload()
            try:
                library.scan(self.db, self.s["library_root"])
            except FileNotFoundError as e:
                if not self.db.one("SELECT 1 FROM episodes LIMIT 1"):
                    raise
                log(f"library scan skipped: {e}")
            cid = self.make_short(drama_slug)
            if not cid:
                raise RuntimeError("لا توجد مقاطع جديدة يمكن صنعها: أضف مسلسلات أو فعّل مسلسلات متوقفة")
            results = self.publish_all(cid) if publish else []
            if publish and not results:
                log("no connected accounts: the video was made but not posted (connect accounts in the dashboard)")
            self._prune_files()
            st = self._save_state(last_run=started, last_clip=cid)
            if st.get("enabled"):
                self._save_state(next_run=started + float(self.s["interval_hours"]) * 3600)
            self._step(f"تم ✔ المقطع #{cid}")
            return {"clip_id": cid, "results": results}
        except Exception as e:
            self.status["last_error"] = str(e)
            log("cycle error:\n" + traceback.format_exc())
            if self.state.get("enabled"):
                self._save_state(next_run=time.time() + 1800)  # retry in 30 min
            return {"error": str(e)}
        finally:
            self.status["busy"] = False
            self.status["step"] = ""
            self.lock.release()

    def _prune_files(self, keep=60):
        """Rendered shorts are only needed until posted; keep the last `keep` on disk for preview."""
        for r in self.db.q("SELECT id, path, cover FROM clips WHERE status='posted' ORDER BY id DESC LIMIT -1 OFFSET ?", keep):
            for p in (r["path"], r["cover"]):
                if p:
                    Path(p).unlink(missing_ok=True)

    # ------------------------------------------------------------------ background loop
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="autopilot")
        self._thread.start()

    def _loop(self):
        last_stats = 0.0
        while True:
            try:
                st = self.state
                if st.get("enabled") and st.get("next_run") and time.time() >= st["next_run"]:
                    self.cycle()
                if time.time() - last_stats > 6 * 3600:
                    last_stats = time.time()
                    if self.db.one("SELECT 1 FROM posts WHERE status='published' LIMIT 1"):
                        self.reload()
                        log(f"stats refreshed for {self.bot.brain.refresh_stats()} posts")
            except Exception:
                log("autopilot loop error:\n" + traceback.format_exc())
            time.sleep(20)
