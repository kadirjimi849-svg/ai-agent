"""Dashboard:  python -m bot web   ->  http://localhost:8080

Runs the autopilot in the background and gives a browser UI to connect the accounts,
manage the series library, change settings, watch the log and preview/post shorts.
Listens on 127.0.0.1 only: tokens never leave this computer except to the platforms themselves.
"""
import json
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from flask import Flask, abort, jsonify, redirect, request, send_file

from . import accounts, library, logs, oauth, settings
from .autopilot import Autopilot
from .runner import Bot

HERE = Path(__file__).resolve().parent


def create_app(cfg, port=8080):
    logs.set_file(Path(cfg["paths"]["data"]) / "bot.log")
    bot = Bot(cfg)
    pilot = Autopilot(bot)
    db = bot.db
    base = f"http://localhost:{port}"
    app = Flask(__name__)
    app.config["JSON_AS_ASCII"] = False

    def body():
        return request.get_json(silent=True) or {}

    def ok(**kw):
        return jsonify({"ok": True, **kw})

    def fail(msg, code=400):
        return jsonify({"ok": False, "error": str(msg)}), code

    @app.errorhandler(oauth.OAuthError)
    def _oauth_err(e):
        if request.path.startswith("/api/"):
            return fail(e)
        return redirect(f"/?err={quote(str(e))}#accounts")

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index():
        return send_file(HERE / "web" / "index.html")

    # ------------------------------------------------------------------ state
    @app.get("/api/state")
    def state():
        s = pilot.reload()
        n = lambda sql, *a: (db.one(sql, *a) or [0])[0]  # noqa: E731
        plat = {r["platform"]: {"posts": r["n"], "views": r["v"] or 0} for r in db.q(
            "SELECT platform, COUNT(*) n, SUM(views) v FROM posts WHERE status='published' GROUP BY platform")}
        return jsonify({
            "now": time.time(),
            "settings": settings.public(s),
            "autopilot": {**pilot.state, **pilot.status},
            "accounts": [accounts.public(a) for a in pilot.bot.cfg["accounts"]],
            "base": base,
            "counts": {
                "series": n("SELECT COUNT(*) FROM dramas"),
                "active": n("SELECT COUNT(*) FROM dramas WHERE active=1"),
                "episodes": n("SELECT COUNT(*) FROM episodes"),
                "clips": n("SELECT COUNT(*) FROM clips"),
                "published": n("SELECT COUNT(*) FROM posts WHERE status='published'"),
                "failed": n("SELECT COUNT(*) FROM posts WHERE status='failed' AND posted_at>?", time.time() - 7 * 86400),
                "views": n("SELECT COALESCE(SUM(views),0) FROM posts"),
                "likes": n("SELECT COALESCE(SUM(likes),0) FROM posts"),
            },
            "platforms": plat,
            "fb_pending": bool(db.get("fb_pending")),
        })

    @app.get("/api/clips")
    def clips():
        limit = min(int(request.args.get("limit", 12)), 100)
        out = []
        for c in db.q("""SELECT c.id, c.hook_text, c.hook_id, c.created_at, c.path, c.start, c.end, e.ep_no, d.title, d.slug
                         FROM clips c JOIN episodes e ON e.id=c.episode_id JOIN dramas d ON d.slug=e.drama_slug
                         ORDER BY c.id DESC LIMIT ?""", limit):
            posts = [dict(p) for p in db.q("""SELECT platform, account, status, url, error, views, likes, comments, shares
                                              FROM posts WHERE clip_id=? ORDER BY id""", c["id"])]
            out.append({**{k: c[k] for k in ("id", "hook_text", "hook_id", "created_at", "ep_no", "title", "slug")},
                        "has_file": bool(c["path"] and Path(c["path"]).exists()), "posts": posts})
        return jsonify(out)

    @app.get("/api/logs")
    def get_logs():
        return jsonify(logs.tail(int(request.args.get("n", 300))))

    # ------------------------------------------------------------------ control
    @app.post("/api/settings")
    def save_settings():
        s = settings.save(db, body())
        pilot.reload()
        st = pilot.state
        if st.get("enabled") and st.get("last_run"):  # interval changed -> move the next run
            pilot._save_state(next_run=max(time.time() + 5, st["last_run"] + float(s["interval_hours"]) * 3600))
        return ok(settings=settings.public(s))

    @app.post("/api/autopilot")
    def toggle_autopilot():
        return ok(state=pilot.enable(bool(body().get("enabled"))))

    @app.post("/api/run")
    def run_now():
        if pilot.status["busy"]:
            return fail("البوت يعمل الآن على مقطع، انتظر حتى ينتهي")
        b = body()
        threading.Thread(target=pilot.cycle, kwargs={"drama_slug": b.get("slug"), "publish": b.get("publish", True)},
                         daemon=True).start()
        return ok()

    @app.post("/api/clips/<int:cid>/publish")
    def publish_clip(cid):
        pilot.reload()
        threading.Thread(target=pilot.publish_all, args=(cid,), daemon=True).start()
        return ok()

    # ------------------------------------------------------------------ library
    @app.post("/api/library/scan")
    def scan():
        s = pilot.reload()
        root = body().get("root") or s["library_root"]
        try:
            res = library.scan(db, root)
        except FileNotFoundError as e:
            return fail(e)
        if root != s["library_root"]:
            settings.save(db, {"library_root": root})
        return ok(**res)

    @app.get("/api/dramas")
    def dramas():
        rows = db.q("""SELECT d.slug, d.title, d.niche, d.priority, d.active,
                         (SELECT COUNT(*) FROM episodes e WHERE e.drama_slug=d.slug) eps,
                         (SELECT COUNT(*) FROM clips c JOIN episodes e ON e.id=c.episode_id WHERE e.drama_slug=d.slug) clips,
                         (SELECT COALESCE(SUM(p.views),0) FROM posts p JOIN clips c ON c.id=p.clip_id
                             JOIN episodes e ON e.id=c.episode_id WHERE e.drama_slug=d.slug) views
                       FROM dramas d ORDER BY d.active DESC, d.title""")
        return jsonify([dict(r) for r in rows])

    @app.post("/api/dramas/<slug>")
    def edit_drama(slug):
        b = body()
        if "active" in b:
            db.x("UPDATE dramas SET active=? WHERE slug=?", int(bool(b["active"])), slug)
        if "priority" in b:
            db.x("UPDATE dramas SET priority=? WHERE slug=?", float(b["priority"]), slug)
        if b.get("niche"):
            db.x("UPDATE dramas SET niche=? WHERE slug=?", b["niche"], slug)
        if "synopsis" in b:
            r = db.one("SELECT extra FROM dramas WHERE slug=?", slug)
            extra = json.loads(r["extra"] or "{}")
            extra["synopsis"] = b["synopsis"]
            db.x("UPDATE dramas SET extra=? WHERE slug=?", json.dumps(extra, ensure_ascii=False), slug)
            db.x("DELETE FROM kv WHERE key LIKE ?", f"aihooks:{slug}:%")
        return ok()

    # ------------------------------------------------------------------ media
    @app.get("/media/<kind>/<int:cid>")
    def media(kind, cid):
        r = db.one("SELECT path, cover FROM clips WHERE id=?", cid)
        p = r and (r["path"] if kind == "video" else r["cover"])
        if not p or not Path(p).exists():
            abort(404)
        return send_file(p, conditional=True)

    # ------------------------------------------------------------------ accounts
    @app.post("/api/accounts/<name>/toggle")
    def acc_toggle(name):
        accounts.set_enabled(db, name, bool(body().get("enabled")))
        return ok()

    @app.delete("/api/accounts/<name>")
    def acc_delete(name):
        accounts.remove(db, name)
        return ok()

    @app.post("/api/accounts/<name>/check")
    def acc_check(name):
        from .publishers import get_publisher
        pilot.reload()
        acc = next((a for a in pilot.bot.cfg["accounts"] if a["name"] == name), None)
        if not acc:
            return fail("not found", 404)
        try:
            return ok(message=get_publisher(acc["platform"], acc, pilot.bot.ctx).check())
        except Exception as e:
            return fail(e)

    @app.get("/connect/<platform>")
    def connect(platform):
        pilot.reload()
        fn = {"youtube": oauth.youtube_url, "facebook": oauth.facebook_url, "instagram": oauth.facebook_url,
              "tiktok": oauth.tiktok_url}.get(platform)
        if not fn:
            abort(404)
        return redirect(fn(db, base))

    @app.get("/oauth/<platform>")
    def callback(platform):
        pilot.reload()
        if request.args.get("error"):
            raise oauth.OAuthError(request.args.get("error_description") or request.args["error"])
        data = oauth.pop_state(db, request.args.get("state"), platform)
        code = request.args.get("code")
        if platform == "youtube":
            ch = oauth.youtube_finish(code, base)
            accounts.upsert(db, f"yt_{ch['channel_id']}", "youtube", ch["title"],
                            {"channel_id": ch["channel_id"], "refresh_token": ch["refresh_token"]})
            return redirect("/?msg=" + quote("تم ربط قناة يوتيوب") + "#accounts")
        if platform == "facebook":
            db.set("fb_pending", oauth.facebook_finish(code, base))
            return redirect("/?fb=1#accounts")
        if platform == "tiktok":
            _save_tiktok(oauth.tiktok_finish(code, base, data.get("verifier")))
            return redirect("/?msg=" + quote("تم ربط حساب تيك توك") + "#accounts")
        abort(404)

    def _save_tiktok(t):
        name = f"tt_{t['open_id']}"
        accounts.upsert(db, name, "tiktok", t["display_name"], {"open_id": t["open_id"], "refresh_token": t["refresh_token"]})
        db.set(f"tt_token:{name}", {"access_token": t["access_token"], "refresh_token": t["refresh_token"], "exp": t["exp"]})

    @app.post("/api/tiktok/paste")
    def tiktok_paste():
        """For a TikTok app whose redirect is an https page of yours: paste the address you landed on."""
        pilot.reload()
        q = parse_qs(urlparse(body().get("url", "")).query)
        data = oauth.pop_state(db, (q.get("state") or [""])[0], "tiktok")
        if not q.get("code"):
            return fail("الرابط لا يحتوي على code")
        _save_tiktok(oauth.tiktok_finish(q["code"][0], base, data.get("verifier")))
        return ok()

    @app.post("/api/fb/token")
    def fb_token():
        """Alternative to the login button: a user token from Graph API Explorer."""
        pilot.reload()
        db.set("fb_pending", oauth.facebook_pages(body().get("token", "").strip()))
        return ok()

    @app.get("/api/fb/pending")
    def fb_pending():
        return jsonify([{k: v for k, v in p.items() if k != "token"} for p in db.get("fb_pending") or []])

    @app.post("/api/fb/connect")
    def fb_connect():
        b = body()
        pages = {p["id"]: p for p in db.get("fb_pending") or []}
        n = 0
        for pid in b.get("pages", []):
            if p := pages.get(pid):
                accounts.upsert(db, f"fb_{pid}", "facebook", p["name"], {"page_id": pid, "token": p["token"]})
                n += 1
        for pid in b.get("instagram", []):
            if (p := pages.get(pid)) and p.get("ig_id"):
                accounts.upsert(db, f"ig_{p['ig_id']}", "instagram", "@" + (p.get("ig_username") or p["ig_id"]),
                                {"ig_user_id": p["ig_id"], "token": p["token"], "page_id": pid})
                n += 1
        db.x("DELETE FROM kv WHERE key='fb_pending'")
        return ok(connected=n)

    @app.post("/api/accounts/manual")
    def acc_manual():
        """Paste a refresh token obtained with tools/*.py (YouTube / TikTok)."""
        b = body()
        plat, tok, label = b.get("platform"), (b.get("refresh_token") or "").strip(), (b.get("label") or "").strip()
        if plat not in ("youtube", "tiktok") or not tok:
            return fail("بيانات ناقصة")
        name = f"{plat[:2]}_{int(time.time())}"
        accounts.upsert(db, name, plat, label or plat, {"refresh_token": tok})
        return ok(name=name)

    pilot.start()
    return app


def serve(cfg, port=8080, open_browser=True):
    app = create_app(cfg, port)
    url = f"http://localhost:{port}"
    logs.log(f"dashboard: {url}")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve as wserve
        wserve(app, host="127.0.0.1", port=port, threads=8)
    except ImportError:
        app.run(host="127.0.0.1", port=port, threaded=True)
