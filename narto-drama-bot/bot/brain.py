"""Learning loop.

Every post's views/likes/shares/comments are pulled back from the platforms.
A performance score per post is normalised per account (a 10k-follower page and a new TikTok
are not comparable), then two UCB bandits decide:
  * which DRAMA gets the next clips (winners get more, new dramas still get explored)
  * which HOOK STYLE is written first
"""
import math
import time

from .publishers import get_publisher


def engagement(p):
    return p["views"] + 8 * p["likes"] + 25 * p["comments"] + 40 * p["shares"]


class Brain:
    def __init__(self, db, cfg, ctx):
        self.db, self.cfg, self.ctx = db, cfg, ctx

    def _norm_scores(self, min_age_h=20):
        """Returns [(post_row, relative_score)] where 1.0 = account average."""
        rows = self.db.q("""SELECT p.*, e.drama_slug, c.hook_id FROM posts p
                            JOIN clips c ON c.id=p.clip_id JOIN episodes e ON e.id=c.episode_id
                            WHERE p.status='published' AND p.stats_at IS NOT NULL AND p.posted_at < ?""",
                         time.time() - min_age_h * 3600)
        by_acc = {}
        for r in rows:
            by_acc.setdefault(r["account"], []).append(r)
        out = []
        for acc, rs in by_acc.items():
            avg = sum(engagement(r) for r in rs) / len(rs) or 1
            out += [(r, engagement(r) / avg) for r in rs]
        return out

    def _ucb(self, arms, key, c=0.8):
        scores = self._norm_scores()
        stats = {a: [0, 0.0] for a in arms}
        for r, s in scores:
            k = r[key]
            if k in stats:
                stats[k][0] += 1
                stats[k][1] += min(s, 5)  # cap outliers
        total = sum(n for n, _ in stats.values()) + 1
        res = {}
        for a, (n, s) in stats.items():
            res[a] = float("inf") if n == 0 else s / n + c * math.sqrt(math.log(total) / n)
        return res

    def pick_drama(self, slugs):
        if not slugs:
            return None
        pri = {r["slug"]: r["priority"] for r in self.db.q("SELECT slug, priority FROM dramas")}
        ucb = self._ucb(slugs, "drama_slug")
        return max(slugs, key=lambda s: (ucb[s] if ucb[s] != float("inf") else 99) * pri.get(s, 1.0))

    def rank_styles(self, styles):
        ucb = self._ucb(styles, "hook_id", c=0.5)
        return sorted(styles, key=lambda s: -(ucb[s] if ucb[s] != float("inf") else 50))

    # ---------- stats collection ----------
    def refresh_stats(self, max_age_days=14):
        accounts = {a["name"]: a for a in self.cfg.get("accounts", [])}
        rows = self.db.q("SELECT * FROM posts WHERE status='published' AND posted_at > ? AND external_id IS NOT NULL",
                         time.time() - max_age_days * 86400)
        n = 0
        for r in rows:
            acc = accounts.get(r["account"])
            if not acc:
                continue
            try:
                s = get_publisher(r["platform"], acc, self.ctx).stats(r["external_id"], r["meta"])
            except Exception as e:
                print(f"[brain] stats {r['platform']} {r['external_id']}: {e}")
                continue
            if s:
                self.db.x("UPDATE posts SET views=?, likes=?, comments=?, shares=?, stats_at=? WHERE id=?",
                          int(s.get("views", r["views"])), int(s.get("likes", r["likes"])),
                          int(s.get("comments", r["comments"])), int(s.get("shares", r["shares"])), time.time(), r["id"])
                n += 1
        return n

    def report(self):
        lines = ["== Dramas (relative score, 1.0 = average) =="]
        agg = {}
        for r, s in self._norm_scores(min_age_h=0):
            for k in (("drama", r["drama_slug"]), ("hook", r["hook_id"]), ("acc", r["account"])):
                a = agg.setdefault(k, [0, 0.0, 0])
                a[0] += 1
                a[1] += s
                a[2] += r["views"]
        for kind, title in (("drama", "Dramas"), ("hook", "Hook styles"), ("acc", "Accounts")):
            if kind != "drama":
                lines.append(f"== {title} ==")
            items = sorted(((k[1], v) for k, v in agg.items() if k[0] == kind), key=lambda kv: -kv[1][1] / kv[1][0])
            for name, (n, s, views) in items:
                lines.append(f"  {name:<32} posts={n:<4} score={s / n:5.2f}  views={views}")
        return "\n".join(lines)
