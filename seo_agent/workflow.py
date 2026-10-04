from __future__ import annotations

import re
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

from .competitor_research import BacklinkDataSource, collect_competitor_backlinks
from .config import MONTHLY_DISCOVERY_TARGET, MONTHLY_SHORTLIST_SIZE
from .content_engine import (ArticleBrief, ArticleWriter, generate_article, plan_anchors)
from .database import BacklinkDatabase
from .models import (AnchorType, Article, ArticleFormat, BacklinkOpportunity, BacklinkRecord,
                     LinkStatus, OutreachEmail, OutreachStatus, TargetWebsite)
from .outreach import MissingPersonalization, OutreachContext, build_sequence
from .quality_control import check_opportunity
from .reporting import MonthlyReport, build_monthly_report
from .scoring import is_recommended, rank_opportunities

Personalizer = Callable[[BacklinkOpportunity], "OutreachContext | None"]
LinkChecker = Callable[[BacklinkRecord, TargetWebsite], LinkStatus]

_FORMAT_FOR_TYPE = {
    "guest_post": ArticleFormat.GUEST_POST,
    "editorial": ArticleFormat.EXPERT_ARTICLE,
    "resource_page": ArticleFormat.RESOURCE_ARTICLE,
    "industry_mention": ArticleFormat.CASE_STUDY,
    "digital_pr": ArticleFormat.DIGITAL_PR,
}


def http_link_checker(rec: BacklinkRecord, site: TargetWebsite) -> LinkStatus:
    """Fetch the published page and look for a link to the client domain."""
    if not rec.published_url:
        return LinkStatus.PENDING
    try:
        req = urllib.request.Request(rec.published_url, headers={"User-Agent": "seo-agent-link-check/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return LinkStatus.LOST
    domain = re.escape(site.domain)
    for tag in re.findall(r"<a\b[^>]*>", html, re.IGNORECASE):
        if re.search(rf"href=[\"']https?://(www\.)?{domain}", tag, re.IGNORECASE):
            return LinkStatus.NOFOLLOW if re.search(r"rel=[\"'][^\"']*(nofollow|sponsored|ugc)",
                                                    tag, re.IGNORECASE) else LinkStatus.LIVE
    return LinkStatus.LOST


@dataclass
class WorkflowResult:
    discovered: int = 0
    rejected_qc: int = 0
    below_threshold: int = 0
    shortlist: list[BacklinkOpportunity] = field(default_factory=list)
    outreach: dict[str, list[OutreachEmail]] = field(default_factory=dict)
    skipped_outreach: list[str] = field(default_factory=list)
    articles: dict[str, Article] = field(default_factory=dict)
    report: MonthlyReport | None = None


class MonthlyWorkflow:
    def __init__(self, site: TargetWebsite, db: BacklinkDatabase,
                 sources: Iterable[BacklinkDataSource] = (),
                 writer: ArticleWriter | None = None,
                 personalizer: Personalizer | None = None,
                 link_checker: LinkChecker = http_link_checker):
        self.site = site
        self.db = db
        self.sources = list(sources)
        self.writer = writer
        self.personalizer = personalizer
        self.link_checker = link_checker

    # Step 1
    def discover(self, extra: Iterable[BacklinkOpportunity] = ()) -> list[BacklinkOpportunity]:
        found = collect_competitor_backlinks(self.site, self.sources)
        seen = {o.website for o in found}
        found += [o for o in extra if o.website not in seen and o.website != self.site.domain]
        return found[:MONTHLY_DISCOVERY_TARGET]

    # Step 2
    def shortlist(self, prospects: list[BacklinkOpportunity], result: WorkflowResult) -> list[BacklinkOpportunity]:
        known = self.db.known_websites()
        passed = []
        for opp in prospects:
            if opp.website in known:
                continue
            if not check_opportunity(opp).accepted:
                result.rejected_qc += 1
                continue
            passed.append(opp)
        ranked = rank_opportunities(passed)
        recommended = [o for o in ranked if is_recommended(o)]
        result.below_threshold = len(ranked) - len(recommended)
        return recommended[:MONTHLY_SHORTLIST_SIZE]

    # Step 3
    def create_outreach(self, shortlist: list[BacklinkOpportunity], result: WorkflowResult,
                        start: date | None = None) -> None:
        for opp in shortlist:
            ctx = self.personalizer(opp) if self.personalizer else None
            if ctx is None:
                result.skipped_outreach.append(f"{opp.website}: no personalization research available")
                continue
            try:
                sequence = build_sequence(ctx, self.site, start)
            except MissingPersonalization as e:
                result.skipped_outreach.append(f"{opp.website}: {e}")
                continue
            result.outreach[opp.website] = sequence
            self.db.upsert(BacklinkRecord(
                website=opp.website, url=opp.url, dr=opp.dr, da=opp.da, traffic=opp.monthly_traffic,
                language=opp.language, country=opp.country, contact_email=opp.contact_email,
                opportunity_type=opp.opportunity_type, status=OutreachStatus.CONTACTED,
                article_title=ctx.content_idea,
            ))

    # Step 4
    def generate_content(self, result: WorkflowResult, topics: dict[str, str] | None = None) -> None:
        """Write articles for prospects that accepted a pitch."""
        if self.writer is None:
            return
        accepted = [r for r in self.db.all(OutreachStatus.ACCEPTED) if not r.anchor_text]
        existing = Counter(self._classify_anchor(a) for a, n in self.db.anchor_counts().items() for _ in range(n))
        anchors = plan_anchors(self.site, len(accepted), existing)
        for rec, anchor in zip(accepted, anchors):
            host = BacklinkOpportunity(
                website=rec.website, url=rec.url, dr=rec.dr, da=rec.da, monthly_traffic=rec.traffic,
                spam_score=0, relevance=100, content_quality=100, language=rec.language,
                country=rec.country, contact_email=rec.contact_email, opportunity_type=rec.opportunity_type)
            topic = (topics or {}).get(rec.website) or rec.article_title or self.site.niche
            brief = ArticleBrief(self.site, host, topic, _FORMAT_FOR_TYPE[rec.opportunity_type.value],
                                 anchor, f"https://{self.site.domain}/")
            article = generate_article(self.writer, brief)
            result.articles[rec.website] = article
            rec.article_title, rec.anchor_text = article.title, article.anchor_text
            self.db.upsert(rec)

    def _classify_anchor(self, text: str) -> AnchorType:
        brand = (self.site.brand_name or self.site.domain).lower()
        t = text.lower()
        if brand in t or self.site.domain.lower() in t:
            return AnchorType.BRANDED
        if t in (k.lower() for k in self.site.keywords):
            return AnchorType.EXACT
        return AnchorType.PARTIAL

    # Step 5
    def track_links(self, checked_on: date | None = None) -> None:
        for rec in self.db.all(OutreachStatus.PUBLISHED):
            self.db.record_link_check(rec.id, self.link_checker(rec, self.site), checked_on)

    # Step 6
    def report(self, month: str, next_opportunities: list[BacklinkOpportunity]) -> MonthlyReport:
        return build_monthly_report(self.db, month, next_opportunities)

    def run(self, month: str, extra_prospects: Iterable[BacklinkOpportunity] = (),
            topics: dict[str, str] | None = None, today: date | None = None) -> WorkflowResult:
        result = WorkflowResult()
        prospects = self.discover(extra_prospects)
        result.discovered = len(prospects)
        result.shortlist = self.shortlist(prospects, result)
        self.create_outreach(result.shortlist, result, today)
        self.generate_content(result, topics)
        self.track_links(today)
        contacted = set(result.outreach)
        result.report = self.report(month, [o for o in result.shortlist if o.website not in contacted])
        return result
