from __future__ import annotations

from dataclasses import dataclass, field

from .config import MAX_SPAM_SCORE, MIN_DA, MIN_DR, MIN_MONTHLY_TRAFFIC
from .models import BacklinkOpportunity

REJECT_FLAGS = {
    "link_farm": "Link farm",
    "automated_directory": "Automated directory",
    "spam_site": "Spam website",
    "pbn": "Private blog network",
    "spam_network": "Part of a spam network",
    "irrelevant_page": "Link would sit on an irrelevant page",
    "sells_links": "Openly sells links",
}

MIN_RELEVANCE = 60


@dataclass
class QCResult:
    accepted: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_opportunity(opp: BacklinkOpportunity) -> QCResult:
    failures: list[str] = []
    warnings: list[str] = []

    for flag in sorted(opp.flags & REJECT_FLAGS.keys()):
        failures.append(REJECT_FLAGS[flag])
    if not opp.indexed:
        failures.append("Website is not indexed")
    if not opp.natural_profile:
        failures.append("Unnatural backlink profile")
    if opp.relevance < MIN_RELEVANCE:
        failures.append(f"Niche relevance {opp.relevance:.0f} below {MIN_RELEVANCE}")
    if opp.monthly_traffic < MIN_MONTHLY_TRAFFIC:
        failures.append(f"Organic traffic {opp.monthly_traffic} below {MIN_MONTHLY_TRAFFIC}")
    if opp.spam_score > MAX_SPAM_SCORE:
        failures.append(f"Spam score {opp.spam_score} above {MAX_SPAM_SCORE}")
    if opp.dr < MIN_DR:
        failures.append(f"DR {opp.dr} below {MIN_DR}")
    if opp.da < MIN_DA:
        failures.append(f"DA {opp.da} below {MIN_DA}")
    if "nofollow" in opp.flags:
        warnings.append("Link will likely be nofollow")

    return QCResult(accepted=not failures, failures=failures, warnings=warnings)


@dataclass
class PlacementCheck:
    """Post-publication verification of a live link."""

    page_indexed: bool
    link_found: bool
    dofollow: bool
    in_body_content: bool
    page_relevant: bool


def check_placement(p: PlacementCheck) -> QCResult:
    failures = []
    if not p.link_found:
        failures.append("Link not found on page")
    if not p.page_indexed:
        failures.append("Published page not indexed")
    if not p.in_body_content:
        failures.append("Link not placed naturally in body content")
    if not p.page_relevant:
        failures.append("Published page is irrelevant")
    warnings = [] if p.dofollow else ["Link is nofollow"]
    return QCResult(accepted=not failures, failures=failures, warnings=warnings)
