from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class OpportunityType(str, Enum):
    GUEST_POST = "guest_post"
    EDITORIAL = "editorial"
    RESOURCE_PAGE = "resource_page"
    INDUSTRY_MENTION = "industry_mention"
    DIGITAL_PR = "digital_pr"


class ArticleFormat(str, Enum):
    GUEST_POST = "guest_post"
    EXPERT_ARTICLE = "expert_article"
    INDUSTRY_GUIDE = "industry_guide"
    RESOURCE_ARTICLE = "resource_article"
    CASE_STUDY = "case_study"
    DIGITAL_PR = "digital_pr"


class OutreachStatus(str, Enum):
    PROSPECT = "prospect"
    CONTACTED = "contacted"
    FOLLOW_UP = "follow_up"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    REJECTED = "rejected"


class LinkStatus(str, Enum):
    PENDING = "pending"
    LIVE = "live"
    LOST = "lost"
    NOFOLLOW = "nofollow"


class AnchorType(str, Enum):
    BRANDED = "branded"
    PARTIAL = "partial"
    EXACT = "exact"


@dataclass
class TargetWebsite:
    domain: str
    niche: str
    audience: str = ""
    country: str = ""
    language: str = "en"
    brand_name: str = ""
    services: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    competitors: list[str] = field(default_factory=list)


@dataclass
class BacklinkOpportunity:
    """A prospect site. Metric fields are on a 0-100 scale except dr/da/traffic/spam_score."""

    website: str
    url: str
    dr: int
    da: int
    monthly_traffic: int
    spam_score: int
    relevance: float
    content_quality: float
    language: str = "en"
    country: str = ""
    contact_email: str = ""
    opportunity_type: OpportunityType = OpportunityType.GUEST_POST
    indexed: bool = True
    natural_profile: bool = True
    flags: set[str] = field(default_factory=set)
    score: float | None = None


@dataclass
class ArticleSection:
    heading: str
    body: str


@dataclass
class Article:
    title: str
    language: str
    format: ArticleFormat
    introduction: str
    sections: list[ArticleSection]
    conclusion: str
    cta: str
    anchor_text: str
    anchor_type: AnchorType
    link_url: str

    def to_markdown(self) -> str:
        parts = [f"# {self.title}", "", self.introduction, ""]
        for section in self.sections:
            parts += [f"## {section.heading}", "", section.body, ""]
        parts += [self.conclusion, "", self.cta]
        return "\n".join(parts)


@dataclass
class OutreachEmail:
    to: str
    subject: str
    body: str
    language: str
    send_on: date
    sequence_step: int = 0


@dataclass
class BacklinkRecord:
    website: str
    url: str
    dr: int
    da: int
    traffic: int
    language: str
    country: str
    contact_email: str
    opportunity_type: OpportunityType
    status: OutreachStatus = OutreachStatus.PROSPECT
    article_title: str = ""
    published_url: str = ""
    anchor_text: str = ""
    date_created: date = field(default_factory=date.today)
    link_status: LinkStatus = LinkStatus.PENDING
    id: int | None = None
