"""Orchestration: sync catalog -> produce clips -> publish on schedule -> learn."""
import hashlib
import json
import random
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import analyzer, editor
from .brain import Brain
from .copywriter import Copywriter
from .db import DB
from .publishers import get_publisher
from .logs import log
from .storage import Storage


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db = DB(cfg["paths"]["data"])
        self.storage = Storage(cfg)
        self.ctx = {"db": self.db, "storage": self.storage, "cfg": cfg}
        self.brain = Brain(self.db, cfg, self.ctx)
        self.copy = Copywriter(cfg, self.db, self.brain)
        self.tz = ZoneInfo(cfg["timezone"])
        r = cfg.get("render") or {}
        self.font = r.get("font")
        self.accent = tuple(r.get("accent", [229, 9, 20]))

    @property
    def domain(self):
        return self.cfg.get("domain") or ""

    # ------------------------------------------------------------------ catalog
    def sync(self, catalog_path):
        cat = yaml.safe_load(Path(catalog_path).read_text(encoding="utf-8"))
        for d in cat.get("dramas", []):
            extra = {k: d[k] for k in ("synopsis", "hooks", "max_episode") if k in d}
            self.db.x("""INSERT INTO dramas(slug,title,title_en,niche,url,priority,active,extra) VALUES(?,?,?,?,?,?,?,?)
                         ON CONFLICT(slug) DO UPDATE SET title=excluded.title, title_en=excluded.title_en,
                         niche=excluded.niche, url=excluded.url, priority=excluded.priority, active=excluded.active,
                         extra=excluded.extra""",
                      d["slug"], d["title"], d.get("title_en"), d.get("niche", "romance"),
                      d.get("url") or self.cfg.get("drama_url", "https://manodrama.com/drama/{slug}").format(slug=d["slug"]),
                      float(d.get("priority", 1.0)), int(d.get("active", True)), json.dumps(extra, ensure_ascii=False))
            eps = self.storage.list_episodes(d["source"])
            maxep = d.get("max_episode")  # e.g. only promote the free episodes
            for n, src in eps:
                if maxep and n > maxep:
                    continue
                self.db.x("""INSERT INTO episodes(drama_slug,ep_no,src,src_type) VALUES(?,?,?,?)
                             ON CONFLICT(drama_slug,ep_no) DO UPDATE SET src=excluded.src""",
                          d["slug"], n, src, "s3" if src.startswith("s3://") else "local")
            log(f"sync {d['slug']}: {len(eps)} episodes")

    # ------------------------------------------------------------------ production
    def ready_count(self, account):
        return self.db.one(f"""SELECT COUNT(*) n FROM clips c JOIN episodes e ON e.id=c.episode_id
                               JOIN dramas d ON d.slug=e.drama_slug
                               WHERE c.status='ready' AND c.lang=? AND d.active=1 {self._niche_sql(account)}
                               AND NOT EXISTS (SELECT 1 FROM posts p JOIN clips c2 ON c2.id=p.clip_id
                                   WHERE p.account=? AND c2.episode_id=c.episode_id AND c2.start=c.start)""",
                           account.get("lang", "ar"), account["name"])["n"]

    @staticmethod
    def _niche_sql(account):
        niches = account.get("niches") or []
        return "AND d.niche IN (%s)" % ",".join(f"'{n}'" for n in niches) if niches else ""

    def produce(self, drama_slug=None, ep_no=None, count=None, langs=None, niches=None):
        pc = self.cfg.get("production") or {}
        count = count or pc.get("clips_per_episode", 3)
        variants = pc.get("variants", 2)
        langs = langs or sorted({a.get("lang", "ar") for a in self.cfg.get("accounts", [])} or {"ar"})
        if drama_slug:
            drama = self.db.one("SELECT * FROM dramas WHERE slug=?", drama_slug)
        else:
            q = "SELECT slug FROM dramas WHERE active=1"
            if niches:
                q += " AND niche IN (%s)" % ",".join(f"'{n}'" for n in niches)
            slugs = [r["slug"] for r in self.db.q(q)]
            # only dramas that still have unused material
            slugs = [s for s in slugs if self._next_episode(s, count)]
            pick = self.brain.pick_drama(slugs)
            if not pick:
                log("produce: nothing left to cut (add dramas/episodes)")
                return []
            drama = self.db.one("SELECT * FROM dramas WHERE slug=?", pick)
        ep = (self.db.one("SELECT * FROM episodes WHERE drama_slug=? AND ep_no=?", drama["slug"], ep_no)
              if ep_no else self._next_episode(drama["slug"], count))
        if not ep:
            log(f"produce: no episode for {drama['slug']}")
            return []
        log(f"produce: {drama['slug']} ep{ep['ep_no']}")
        src = self.storage.fetch(ep["src"], self.cfg["paths"]["cache"])
        a = json.loads(ep["analysis"]) if ep["analysis"] else None
        if not a:
            a = analyzer.analyze(src)
            self.db.x("UPDATE episodes SET analysis=? WHERE id=?", json.dumps(a), ep["id"])
        taken = [(r["start"], r["end"]) for r in self.db.q("SELECT DISTINCT start,end FROM clips WHERE episode_id=?", ep["id"])]
        plans = analyzer.plan_clips(a, count=count, min_len=pc.get("min_len", 25), max_len=pc.get("max_len", 55),
                                    taken=taken)
        if len(plans) < count:  # episode has no more strong moments -> skip it next time
            a["exhausted"] = 1
            self.db.x("UPDATE episodes SET analysis=? WHERE id=?", json.dumps(a), ep["id"])
        made = []
        vertical = bool(a.get("height") and a.get("width") and a["height"] / a["width"] > 1.5)
        for plan in plans:
            for lang in langs:
                for vi, (style, hook) in enumerate(self.copy.hooks(drama, lang, variants)):
                    title = drama["title"] if lang == "ar" else (drama["title_en"] or drama["title"])
                    label = f"{title} • {'الحلقة' if lang == 'ar' else 'Ep'} {ep['ep_no']}"
                    name = f"{drama['slug']}_e{ep['ep_no']:03d}_{int(plan['start'])}_{lang}_v{vi}"
                    out = Path(self.cfg["paths"]["clips"]) / f"{name}.mp4"
                    try:
                        path, cover, _ = editor.render(
                            src, plan, out, hook_text=hook, label=label, domain=self.domain,
                            end_lines=(*self.copy.end_lines(lang, bool(self.domain)), title), font_path=self.font,
                            has_audio=a.get("has_audio", True), vertical=vertical, accent=self.accent,
                            preset=(self.cfg.get("render") or {}).get("preset", "veryfast"))
                    except Exception as e:
                        log(f"render failed {name}: {e}")
                        continue
                    s3_key = cover_key = None
                    if (self.cfg.get("minio") or {}).get("clips_bucket"):
                        try:
                            s3_key = self.storage.upload(path, f"shorts/{name}.mp4")
                            cover_key = self.storage.upload(cover, f"shorts/{name}.jpg", "image/jpeg")
                        except Exception as e:
                            log(f"minio upload failed (instagram will skip this clip): {e}")
                    cid = self.db.x("""INSERT INTO clips(episode_id,variant,lang,hook_id,hook_text,start,end,teaser_start,
                                       teaser_end,score,path,cover,s3_key,cover_s3_key,status,created_at)
                                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,'ready',?)""",
                                    ep["id"], vi, lang, style, hook, plan["start"], plan["end"], plan["teaser_start"],
                                    plan["teaser_end"], plan["score"], path, cover, s3_key, cover_key, time.time())
                    made.append(cid)
                    log(f"  clip #{cid} [{lang}/{style}] {plan['start']:.0f}-{plan['end']:.0f}s  «{hook}»")
        Storage.prune_cache(self.cfg["paths"]["cache"], (self.cfg.get("production") or {}).get("cache_gb", 20))
        return made

    def _next_episode(self, slug, per_ep):
        return self.db.one("""SELECT e.* FROM episodes e WHERE e.drama_slug=? AND
                              (SELECT COUNT(DISTINCT start) FROM clips c WHERE c.episode_id=e.id) < ?
                              AND COALESCE(json_extract(e.analysis,'$.exhausted'),0)=0
                              ORDER BY e.ep_no LIMIT 1""", slug, per_ep)

    # ------------------------------------------------------------------ publishing
    def pick_clip(self, account):
        last = self.db.one("""SELECT e.drama_slug FROM posts p JOIN clips c ON c.id=p.clip_id
                              JOIN episodes e ON e.id=c.episode_id WHERE p.account=? ORDER BY p.posted_at DESC LIMIT 1""",
                           account["name"])
        rows = self.db.q(f"""SELECT c.*, e.ep_no, e.drama_slug FROM clips c JOIN episodes e ON e.id=c.episode_id
                             JOIN dramas d ON d.slug=e.drama_slug
                             WHERE c.status='ready' AND c.lang=? AND d.active=1 {self._niche_sql(account)}
                             AND NOT EXISTS (SELECT 1 FROM posts p JOIN clips c2 ON c2.id=p.clip_id
                                 WHERE p.account=? AND c2.episode_id=c.episode_id AND c2.start=c.start)""",
                         account.get("lang", "ar"), account["name"])
        if not rows:
            return None
        slugs = sorted({r["drama_slug"] for r in rows})
        if last and len(slugs) > 1:
            slugs = [s for s in slugs if s != last["drama_slug"]]
        drama = self.brain.pick_drama(slugs)
        cands = [r for r in rows if r["drama_slug"] == drama]
        # funnel: early episodes first, then analyzer score; spread variants across platforms
        pidx = ["facebook", "instagram", "tiktok", "youtube"].index(account["platform"])
        return sorted(cands, key=lambda r: (r["ep_no"], -r["score"], (r["variant"] - pidx) % 2))[0]

    def publish_next(self, account, clip_id=None, dry=None):
        dry = self.cfg.get("dry_run", True) if dry is None else dry
        clip = (self.db.one("SELECT c.*, e.ep_no, e.drama_slug FROM clips c JOIN episodes e ON e.id=c.episode_id WHERE c.id=?",
                            clip_id) if clip_id else self.pick_clip(account))
        if not clip:
            log(f"[{account['name']}] no clip available")
            return None
        drama = self.db.one("SELECT * FROM dramas WHERE slug=?", clip["drama_slug"])
        texts = self.copy.caption(drama=drama, ep_no=clip["ep_no"], hook=clip["hook_text"], lang=clip["lang"],
                                  platform=account["platform"], account=account["name"], clip_id=clip["id"],
                                  domain=self.domain)
        if dry:
            log(f"[DRY] {account['name']} <- clip #{clip['id']} {Path(clip['path']).name}\n{texts['caption']}\n")
            self.db.add_post(clip["id"], account["platform"], account["name"], "dry_run")
            return {"dry": True}
        try:
            res = get_publisher(account["platform"], account, self.ctx).publish(clip["path"], clip["cover"], texts, clip)
            self.db.add_post(clip["id"], account["platform"], account["name"], "published", res["id"], res.get("url"),
                             meta=res.get("meta"))
            log(f"[{account['name']}] published clip #{clip['id']} -> {res.get('url')}")
            return res
        except Exception as e:
            self.db.add_post(clip["id"], account["platform"], account["name"], "failed", error=str(e)[:1000])
            log(f"[{account['name']}] FAILED clip #{clip['id']}: {e}")
            return None

    # ------------------------------------------------------------------ scheduler
    def _slot_time(self, account, day, hhmm):
        h, m = map(int, hhmm.split(":"))
        jitter = account.get("jitter_min", self.cfg.get("jitter_min", 12))
        seed = int(hashlib.md5(f"{account['name']}{day}{hhmm}".encode()).hexdigest(), 16)
        return datetime(day.year, day.month, day.day, h, m, tzinfo=self.tz) + timedelta(minutes=seed % (jitter + 1))

    def due_slots(self, now):
        due = []
        for acc in self.cfg.get("accounts", []):
            if not acc.get("enabled", True):
                continue
            today = now.date()
            posted_today = self.db.one("SELECT COUNT(*) n FROM posts WHERE account=? AND status IN ('published','dry_run') "
                                       "AND posted_at>=?", acc["name"],
                                       datetime(today.year, today.month, today.day, tzinfo=self.tz).timestamp())["n"]
            for hhmm in acc.get("slots", []):
                t = self._slot_time(acc, today, hhmm)
                key = f"slot:{acc['name']}:{today}:{hhmm}"
                if t <= now < t + timedelta(hours=2) and not self.db.get(key):
                    if posted_today >= acc.get("daily_cap", 8):
                        self.db.set(key, "capped")
                        continue
                    due.append((acc, key))
        return due

    def run_forever(self):
        pc = self.cfg.get("production") or {}
        last_stats = 0
        log(f"bot running  dry_run={self.cfg.get('dry_run')}  accounts={[a['name'] for a in self.cfg.get('accounts', [])]}")
        while True:
            try:
                now = datetime.now(self.tz)
                for acc, key in self.due_slots(now):
                    self.db.set(key, "done")
                    self.publish_next(acc)
                # keep a buffer of ready clips for every account
                for acc in self.cfg.get("accounts", []):
                    if acc.get("enabled", True) and self.ready_count(acc) < pc.get("buffer", 6):
                        if not self.produce(langs=[acc.get("lang", "ar")], niches=acc.get("niches")):
                            break
                        break  # one episode per loop so publishing stays on time
                if time.time() - last_stats > (self.cfg.get("stats_every_h", 6)) * 3600:
                    n = self.brain.refresh_stats()
                    log(f"stats refreshed for {n} posts")
                    last_stats = time.time()
            except Exception:
                log("loop error:\n" + traceback.format_exc())
            time.sleep(60 + random.randint(0, 20))
