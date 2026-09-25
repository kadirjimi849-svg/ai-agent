"""SQLite state: dramas, episodes, clips, posts, key/value (tokens, slot locks)."""
import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dramas(
  slug TEXT PRIMARY KEY, title TEXT, title_en TEXT, niche TEXT, url TEXT,
  priority REAL DEFAULT 1.0, active INTEGER DEFAULT 1, extra TEXT);
CREATE TABLE IF NOT EXISTS episodes(
  id INTEGER PRIMARY KEY, drama_slug TEXT, ep_no INTEGER, src TEXT, src_type TEXT,
  analysis TEXT, UNIQUE(drama_slug, ep_no));
CREATE TABLE IF NOT EXISTS clips(
  id INTEGER PRIMARY KEY, episode_id INTEGER, variant INTEGER, lang TEXT,
  hook_id TEXT, hook_text TEXT, start REAL, end REAL, teaser_start REAL, teaser_end REAL,
  score REAL, path TEXT, cover TEXT, s3_key TEXT, cover_s3_key TEXT,
  status TEXT DEFAULT 'ready', created_at REAL);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY, clip_id INTEGER, platform TEXT, account TEXT,
  external_id TEXT, url TEXT, status TEXT, error TEXT, posted_at REAL,
  views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0,
  shares INTEGER DEFAULT 0, stats_at REAL, meta TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS accounts(
  name TEXT PRIMARY KEY, platform TEXT, label TEXT, data TEXT, enabled INTEGER DEFAULT 1, created_at REAL);
CREATE INDEX IF NOT EXISTS ix_posts_acc ON posts(account, posted_at);
CREATE INDEX IF NOT EXISTS ix_clips_ep ON clips(episode_id);
"""


class DB:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "bot.sqlite3"
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        self.lock = threading.RLock()  # the dashboard and the autopilot thread share this connection

    def q(self, sql, *a):
        with self.lock:
            return self.con.execute(sql, a).fetchall()

    def one(self, sql, *a):
        with self.lock:
            return self.con.execute(sql, a).fetchone()

    def x(self, sql, *a):
        with self.lock:
            cur = self.con.execute(sql, a)
            self.con.commit()
            return cur.lastrowid

    # key/value
    def get(self, key, default=None):
        r = self.one("SELECT value FROM kv WHERE key=?", key)
        return json.loads(r["value"]) if r else default

    def set(self, key, value):
        self.x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               key, json.dumps(value, ensure_ascii=False))

    def add_post(self, clip_id, platform, account, status, external_id=None, url=None, error=None, meta=None):
        return self.x("INSERT INTO posts(clip_id,platform,account,external_id,url,status,error,posted_at,meta)"
                      " VALUES(?,?,?,?,?,?,?,?,?)", clip_id, platform, account, external_id, url, status,
                      error, time.time(), json.dumps(meta or {}, ensure_ascii=False))
