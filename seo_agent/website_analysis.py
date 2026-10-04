from __future__ import annotations

from dataclasses import dataclass, field

from .config import MIN_DR, PREFERRED_DR
from .models import ArticleFormat, BacklinkOpportunity, OpportunityType, TargetWebsite


@dataclass
class BacklinkProfile:
    referring_domains: int = 0
    high_authority_domains: int = 0
    branded_anchor_ratio: float = 0.0
    dofollow_ratio: float = 0.0


@dataclass
class OpportunityReport:
    site: TargetWebsite
    profile: BacklinkProfile
    gaps: list[str] = field(default_factory=list)
    strategy: list[str] = field(default_factory=list)
    content_topics: list[tuple[str, ArticleFormat]] = field(default_factory=list)
    opportunity_mix: dict[str, int] = field(default_factory=dict)

    def to_markdown(self) -> str:
        s, p = self.site, self.profile
        lines = [
            f"# SEO Opportunity Report — {s.domain}",
            "",
            f"- **Niche:** {s.niche}",
            f"- **Audience:** {s.audience or 'n/a'}",
            f"- **Country / Language:** {s.country or 'n/a'} / {s.language}",
            f"- **Services:** {', '.join(s.services) or 'n/a'}",
            f"- **Keywords:** {', '.join(s.keywords) or 'n/a'}",
            f"- **Competitors:** {', '.join(s.competitors) or 'n/a'}",
            "",
            "## Current backlink profile",
            f"- Referring domains: {p.referring_domains}",
            f"- DR {MIN_DR}+ referring domains: {p.high_authority_domains}",
            f"- Branded anchor ratio: {p.branded_anchor_ratio:.0%}",
            f"- Dofollow ratio: {p.dofollow_ratio:.0%}",
            "",
            "## Gaps",
            *[f"- {g}" for g in self.gaps],
            "",
            "## Link building strategy",
            *[f"{i}. {st}" for i, st in enumerate(self.strategy, 1)],
            "",
            "## Competitor opportunity mix",
            *[f"- {k}: {v}" for k, v in self.opportunity_mix.items()],
            "",
            "## Content topics",
            *[f"- {t} ({fmt.value})" for t, fmt in self.content_topics],
        ]
        return "\n".join(lines)


def _topics(site: TargetWebsite) -> list[tuple[str, ArticleFormat]]:
    topics: list[tuple[str, ArticleFormat]] = []
    subjects = site.keywords[:4] or [site.niche]
    ar = site.language == "ar"
    for kw in subjects:
        if ar:
            topics += [
                (f"الدليل الشامل لـ {kw}", ArticleFormat.INDUSTRY_GUIDE),
                (f"أخطاء شائعة في {kw} وكيف تتجنبها", ArticleFormat.EXPERT_ARTICLE),
                (f"دراسة حالة: كيف حققت شركة نتائج ملموسة مع {kw}", ArticleFormat.CASE_STUDY),
            ]
        else:
            topics += [
                (f"The Complete Guide to {kw}", ArticleFormat.INDUSTRY_GUIDE),
                (f"Common {kw} Mistakes and How to Avoid Them", ArticleFormat.EXPERT_ARTICLE),
                (f"Case Study: Measurable Results with {kw}", ArticleFormat.CASE_STUDY),
            ]
    year_topic = (f"اتجاهات {site.niche} لهذا العام: بيانات وأرقام" if ar
                  else f"{site.niche} Trends This Year: Data and Insights")
    resource_topic = (f"أفضل المصادر المفيدة في {site.niche}" if ar
                      else f"The Best {site.niche} Resources, Curated")
    topics += [(year_topic, ArticleFormat.DIGITAL_PR), (resource_topic, ArticleFormat.RESOURCE_ARTICLE)]
    return topics


def analyze_website(
    site: TargetWebsite,
    profile: BacklinkProfile,
    competitor_opportunities: list[BacklinkOpportunity] | None = None,
) -> OpportunityReport:
    competitor_opportunities = competitor_opportunities or []
    gaps: list[str] = []
    if profile.high_authority_domains < 10:
        gaps.append(f"Few DR {MIN_DR}+ referring domains ({profile.high_authority_domains})")
    if profile.branded_anchor_ratio < 0.6:
        gaps.append("Anchor profile is over-optimized; branded share is below 60%")
    if profile.dofollow_ratio < 0.5:
        gaps.append("Less than half of existing links are dofollow")

    mix: dict[str, int] = {t.value: 0 for t in OpportunityType}
    for opp in competitor_opportunities:
        mix[opp.opportunity_type.value] += 1
    preferred = sum(1 for o in competitor_opportunities if o.dr >= PREFERRED_DR)
    if competitor_opportunities:
        gaps.append(f"{len(competitor_opportunities)} competitor referring domains at DR {MIN_DR}+ "
                    f"({preferred} at DR {PREFERRED_DR}+) do not yet link to {site.domain}")

    strategy = [
        f"Prioritize DR {PREFERRED_DR}+ editorial and guest post placements in the {site.niche} niche.",
        "Replicate competitor links from resource pages and industry mentions where our content is stronger.",
        "Publish one linkable data-driven asset per quarter to support digital PR outreach.",
        "Keep anchors ~70% branded, ~20% partial match, ≤10% exact match.",
        f"Produce all content and outreach in {'Arabic' if site.language == 'ar' else 'English'} "
        f"for {site.country or 'the target market'}.",
    ]
    return OpportunityReport(site, profile, gaps, strategy, _topics(site), mix)
