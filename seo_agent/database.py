from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .models import BacklinkRecord, LinkStatus, OpportunityType, OutreachStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS backlinks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    website          TEXT NOT NULL,
    url              TEXT NOT NULL,
    dr               INTEGER NOT NULL,
    da               INTEGER NOT NULL,
    traffic          INTEGER NOT NULL,
    language         TEXT NOT NULL,
    country          TEXT NOT NULL DEFAULT '',
    contact_email    TEXT NOT NULL DEFAULT '',
    opportunity_type TEXT NOT NULL,
    status           TEXT NOT NULL,
    article_title    TEXT NOT NULL DEFAULT '',
    published_url    TEXT NOT NULL DEFAULT '',
    anchor_text      TEXT NOT NULL DEFAULT '',
    date_created     TEXT NOT NULL,
    link_status      TEXT NOT NULL,
    UNIQUE (website, url)
);

CREATE TABLE IF NOT EXISTS link_checks (
    backlink_id INTEGER NOT NULL REFERENCES backlinks(id),
    checked_on  TEXT NOT NULL,
    link_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_metrics (
    month           TEXT PRIMARY KEY,
    dr              INTEGER NOT NULL,
    organic_traffic INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS keyword_rankings (
    month    TEXT NOT NULL,
    keyword  TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (month, keyword)
);
"""

_COLUMNS = ("website", "url", "dr", "da", "traffic", "language", "country", "contact_email",
            "opportunity_type", "status", "article_title", "published_url", "anchor_text",
            "date_created", "link_status")


class BacklinkDatabase:
    def __init__(self, path: str | Path = "backlinks.db"):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -------------------------------------------------------------- backlinks

    def upsert(self, rec: BacklinkRecord) -> int:
        values = (rec.website, rec.url, rec.dr, rec.da, rec.traffic, rec.language, rec.country,
                  rec.contact_email, rec.opportunity_type.value, rec.status.value, rec.article_title,
                  rec.published_url, rec.anchor_text, rec.date_created.isoformat(), rec.link_status.value)
        updates = ", ".join(f"{c}=excluded.{c}" for c in _COLUMNS if c not in ("website", "url", "date_created"))
        cur = self.conn.execute(
            f"INSERT INTO backlinks ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' * len(_COLUMNS))}) "
            f"ON CONFLICT(website, url) DO UPDATE SET {updates} RETURNING id",
            values,
        )
        rec.id = cur.fetchone()[0]
        self.conn.commit()
        return rec.id

    def update_status(self, backlink_id: int, status: OutreachStatus) -> None:
        self.conn.execute("UPDATE backlinks SET status=? WHERE id=?", (status.value, backlink_id))
        self.conn.commit()

    def mark_published(self, backlink_id: int, published_url: str, article_title: str, anchor_text: str) -> None:
        self.conn.execute(
            "UPDATE backlinks SET status=?, published_url=?, article_title=?, anchor_text=? WHERE id=?",
            (OutreachStatus.PUBLISHED.value, published_url, article_title, anchor_text, backlink_id),
        )
        self.conn.commit()

    def record_link_check(self, backlink_id: int, status: LinkStatus, checked_on: date | None = None) -> None:
        checked_on = checked_on or date.today()
        self.conn.execute("INSERT INTO link_checks VALUES (?, ?, ?)",
                          (backlink_id, checked_on.isoformat(), status.value))
        self.conn.execute("UPDATE backlinks SET link_status=? WHERE id=?", (status.value, backlink_id))
        self.conn.commit()

    def get(self, backlink_id: int) -> BacklinkRecord | None:
        row = self.conn.execute("SELECT * FROM backlinks WHERE id=?", (backlink_id,)).fetchone()
        return self._to_record(row) if row else None

    def all(self, status: OutreachStatus | None = None) -> list[BacklinkRecord]:
        if status:
            rows = self.conn.execute("SELECT * FROM backlinks WHERE status=? ORDER BY id", (status.value,))
        else:
            rows = self.conn.execute("SELECT * FROM backlinks ORDER BY id")
        return [self._to_record(r) for r in rows]

    def known_websites(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT website FROM backlinks")}

    def anchor_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT anchor_text, COUNT(*) FROM backlinks WHERE anchor_text != '' GROUP BY anchor_text")
        return {r[0]: r[1] for r in rows}

    def transitions(self, start: date, end: date, to_status: LinkStatus) -> list[BacklinkRecord]:
        """Backlinks that moved into `to_status` during [start, end)."""
        rows = self.conn.execute(
            "SELECT backlink_id, checked_on, link_status FROM link_checks "
            "WHERE checked_on < ? ORDER BY backlink_id, checked_on, rowid", (end.isoformat(),))
        previous: dict[int, str] = {}
        hit: list[int] = []
        lo = start.isoformat()
        for backlink_id, checked_on, status in rows:
            if (status == to_status.value and previous.get(backlink_id) != status
                    and checked_on >= lo and backlink_id not in hit):
                hit.append(backlink_id)
            previous[backlink_id] = status
        return [self.get(i) for i in hit]

    # -------------------------------------------------------------- site metrics

    def record_site_metrics(self, month: str, dr: int, organic_traffic: int) -> None:
        self.conn.execute("INSERT OR REPLACE INTO site_metrics VALUES (?, ?, ?)", (month, dr, organic_traffic))
        self.conn.commit()

    def site_metrics(self, month: str) -> tuple[int, int] | None:
        row = self.conn.execute("SELECT dr, organic_traffic FROM site_metrics WHERE month=?", (month,)).fetchone()
        return (row[0], row[1]) if row else None

    def record_rankings(self, month: str, rankings: dict[str, int]) -> None:
        self.conn.executemany("INSERT OR REPLACE INTO keyword_rankings VALUES (?, ?, ?)",
                              [(month, k, p) for k, p in rankings.items()])
        self.conn.commit()

    def rankings(self, month: str) -> dict[str, int]:
        rows = self.conn.execute("SELECT keyword, position FROM keyword_rankings WHERE month=?", (month,))
        return {r[0]: r[1] for r in rows}

    @staticmethod
    def _to_record(row: sqlite3.Row) -> BacklinkRecord:
        return BacklinkRecord(
            id=row["id"], website=row["website"], url=row["url"], dr=row["dr"], da=row["da"],
            traffic=row["traffic"], language=row["language"], country=row["country"],
            contact_email=row["contact_email"], opportunity_type=OpportunityType(row["opportunity_type"]),
            status=OutreachStatus(row["status"]), article_title=row["article_title"],
            published_url=row["published_url"], anchor_text=row["anchor_text"],
            date_created=date.fromisoformat(row["date_created"]), link_status=LinkStatus(row["link_status"]),
        )
