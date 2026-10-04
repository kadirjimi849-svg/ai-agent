from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .database import BacklinkDatabase
from .models import BacklinkOpportunity, BacklinkRecord, LinkStatus


def month_bounds(month: str) -> tuple[date, date]:
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return start, end


def previous_month(month: str) -> str:
    year, mon = map(int, month.split("-"))
    return f"{year - (mon == 1)}-{(mon - 2) % 12 + 1:02d}"


@dataclass
class MonthlyReport:
    month: str
    new_backlinks: list[BacklinkRecord]
    lost_backlinks: list[BacklinkRecord]
    dr: tuple[int | None, int | None]
    traffic: tuple[int | None, int | None]
    keyword_movement: list[tuple[str, int | None, int]]
    next_opportunities: list[BacklinkOpportunity] = field(default_factory=list)

    @staticmethod
    def _delta(pair: tuple[int | None, int | None]) -> str:
        before, after = pair
        if after is None:
            return "n/a"
        if before is None:
            return f"{after:,}"
        return f"{before:,} → {after:,} ({after - before:+,})"

    def to_markdown(self) -> str:
        lines = [f"# Monthly SEO Link Building Report — {self.month}", "",
                 f"## New backlinks ({len(self.new_backlinks)})"]
        lines += [f"- {r.website} (DR {r.dr}) — {r.published_url or r.url} — anchor: \"{r.anchor_text}\""
                  for r in self.new_backlinks] or ["- None"]
        lines += ["", f"## Lost backlinks ({len(self.lost_backlinks)})"]
        lines += [f"- {r.website} (DR {r.dr}) — {r.published_url or r.url}"
                  for r in self.lost_backlinks] or ["- None"]
        lines += ["", "## Authority growth", f"- Domain Rating: {self._delta(self.dr)}",
                  "", "## Traffic impact", f"- Organic traffic: {self._delta(self.traffic)}",
                  "", "## Keyword movement"]
        for kw, before, after in self.keyword_movement:
            if before is None:
                lines.append(f"- {kw}: new at #{after}")
            else:
                change = before - after
                arrow = "▲" if change > 0 else "▼" if change < 0 else "="
                lines.append(f"- {kw}: #{before} → #{after} ({arrow}{abs(change)})")
        if not self.keyword_movement:
            lines.append("- No ranking data")
        lines += ["", "## Next opportunities"]
        lines += [f"- {o.website} — DR {o.dr}, score {o.score}, {o.opportunity_type.value}"
                  for o in self.next_opportunities] or ["- None queued"]
        return "\n".join(lines)


def build_monthly_report(db: BacklinkDatabase, month: str,
                         next_opportunities: list[BacklinkOpportunity] | None = None) -> MonthlyReport:
    start, end = month_bounds(month)
    prev = previous_month(month)
    cur_m, prev_m = db.site_metrics(month), db.site_metrics(prev)
    cur_r, prev_r = db.rankings(month), db.rankings(prev)
    movement = sorted(((kw, prev_r.get(kw), pos) for kw, pos in cur_r.items()),
                      key=lambda t: (t[1] or 101) - t[2], reverse=True)
    return MonthlyReport(
        month=month,
        new_backlinks=db.transitions(start, end, LinkStatus.LIVE),
        lost_backlinks=db.transitions(start, end, LinkStatus.LOST),
        dr=(prev_m[0] if prev_m else None, cur_m[0] if cur_m else None),
        traffic=(prev_m[1] if prev_m else None, cur_m[1] if cur_m else None),
        keyword_movement=movement,
        next_opportunities=(next_opportunities or [])[:10],
    )
