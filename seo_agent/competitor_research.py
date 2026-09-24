from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Iterable, Protocol

from .config import MIN_DR, PREFERRED_DR
from .models import BacklinkOpportunity, OpportunityType, TargetWebsite


class BacklinkDataSource(Protocol):
    def referring_domains(self, competitor: str) -> list[BacklinkOpportunity]: ...


class DataSourceNotConfigured(RuntimeError):
    pass


class AhrefsClient:
    """Ahrefs API v3 client. Requires AHREFS_API_KEY; wire up the HTTP call for your plan."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("AHREFS_API_KEY")

    def referring_domains(self, competitor: str) -> list[BacklinkOpportunity]:
        if not self.api_key:
            raise DataSourceNotConfigured("Set AHREFS_API_KEY to use the Ahrefs data source")
        raise NotImplementedError("Implement the Ahrefs site-explorer/refdomains request for your plan")


class SemrushClient:
    """Semrush Backlinks API client. Requires SEMRUSH_API_KEY."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("SEMRUSH_API_KEY")

    def referring_domains(self, competitor: str) -> list[BacklinkOpportunity]:
        if not self.api_key:
            raise DataSourceNotConfigured("Set SEMRUSH_API_KEY to use the Semrush data source")
        raise NotImplementedError("Implement the Semrush backlinks_refdomains request for your plan")


class CsvExportSource:
    """Reads a referring-domains CSV exported from Ahrefs/Semrush (one file per competitor)."""

    COLUMNS = ("website", "url", "dr", "da", "monthly_traffic", "spam_score",
               "relevance", "content_quality", "language", "country",
               "contact_email", "opportunity_type")

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def referring_domains(self, competitor: str) -> list[BacklinkOpportunity]:
        path = self.directory / f"{competitor}.csv"
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as fh:
            return [self._row(r) for r in csv.DictReader(fh)]

    @staticmethod
    def _row(r: dict[str, str]) -> BacklinkOpportunity:
        flags = {f.strip() for f in r.get("flags", "").split(";") if f.strip()}
        return BacklinkOpportunity(
            website=r["website"],
            url=r.get("url") or f"https://{r['website']}",
            dr=int(r["dr"]),
            da=int(r.get("da") or r["dr"]),
            monthly_traffic=int(r["monthly_traffic"]),
            spam_score=int(r.get("spam_score") or 0),
            relevance=float(r.get("relevance") or 0),
            content_quality=float(r.get("content_quality") or 0),
            language=r.get("language") or "en",
            country=r.get("country", ""),
            contact_email=r.get("contact_email", ""),
            opportunity_type=OpportunityType(r.get("opportunity_type") or "guest_post"),
            indexed=r.get("indexed", "true").lower() != "false",
            natural_profile=r.get("natural_profile", "true").lower() != "false",
            flags=flags,
        )


def search_operator_queries(site: TargetWebsite) -> list[str]:
    """Google search-operator footprints for manual prospect discovery."""
    queries = []
    for kw in site.keywords[:5] or [site.niche]:
        queries += [
            f'"{kw}" "write for us"',
            f'"{kw}" "guest post guidelines"',
            f'"{kw}" "contribute" OR "contributor"',
            f'"{kw}" inurl:resources',
            f'"{kw}" intitle:"useful links" OR intitle:"resources"',
            f'"{kw}" "expert roundup"',
        ]
    for comp in site.competitors:
        queries.append(f'"{comp}" -site:{comp}')
    if site.language == "ar":
        queries += [f'"{site.niche}" "اكتب لنا"', f'"{site.niche}" "مقال ضيف"']
    return queries


def collect_competitor_backlinks(
    site: TargetWebsite, sources: Iterable[BacklinkDataSource]
) -> list[BacklinkOpportunity]:
    """Merge referring domains across competitors/sources, dedupe by domain, drop sub-DR70."""
    by_domain: dict[str, BacklinkOpportunity] = {}
    for source in sources:
        for competitor in site.competitors:
            for opp in source.referring_domains(competitor):
                if opp.website == site.domain or opp.dr < MIN_DR:
                    continue
                existing = by_domain.get(opp.website)
                if existing is None or opp.dr > existing.dr:
                    by_domain[opp.website] = opp
    return sorted(by_domain.values(), key=lambda o: (o.dr >= PREFERRED_DR, o.dr), reverse=True)
