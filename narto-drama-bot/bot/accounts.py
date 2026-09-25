"""Accounts connected from the dashboard (tokens live in the local SQLite file, never in the browser).

Each row becomes the same dict shape the publishers already use for config.yaml accounts:
  facebook  {page_id, token}
  instagram {ig_user_id, token}
  youtube   {refresh_token}
  tiktok    {refresh_token}
"""
import json
import time

PLATFORMS = ("youtube", "facebook", "instagram", "tiktok")
SECRET_FIELDS = ("token", "refresh_token", "access_token")


def upsert(db, name, platform, label, data: dict, enabled=True):
    db.x("""INSERT INTO accounts(name,platform,label,data,enabled,created_at) VALUES(?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET platform=excluded.platform, label=excluded.label, data=excluded.data""",
         name, platform, label, json.dumps(data, ensure_ascii=False), int(enabled), time.time())
    # a re-connect must not keep an old cached access token
    db.x("DELETE FROM kv WHERE key IN (?,?)", f"yt_token:{name}", f"tt_token:{name}")


def all_accounts(db, only_enabled=False) -> list[dict]:
    rows = db.q("SELECT * FROM accounts" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY platform, label")
    out = []
    for r in rows:
        d = json.loads(r["data"] or "{}")
        out.append({**d, "name": r["name"], "platform": r["platform"], "label": r["label"],
                    "enabled": bool(r["enabled"]), "lang": d.get("lang", "ar"), "first_comment": True})
    return out


def public(acc: dict) -> dict:
    return {k: v for k, v in acc.items() if k not in SECRET_FIELDS}


def set_enabled(db, name, enabled: bool):
    db.x("UPDATE accounts SET enabled=? WHERE name=?", int(enabled), name)


def remove(db, name):
    db.x("DELETE FROM accounts WHERE name=?", name)
    db.x("DELETE FROM kv WHERE key IN (?,?)", f"yt_token:{name}", f"tt_token:{name}")
