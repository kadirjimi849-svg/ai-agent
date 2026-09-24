from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .config import ANCHOR_DISTRIBUTION, INTRO_WORD_RANGE
from .models import (AnchorType, Article, ArticleFormat, ArticleSection,
                     BacklinkOpportunity, TargetWebsite)

DEFAULT_MODEL = "claude-opus-5"
MAX_KEYWORD_DENSITY = 0.025
MIN_H2_SECTIONS = 3


# ---------------------------------------------------------------- anchors

@dataclass
class AnchorPlan:
    text: str
    type: AnchorType


def plan_anchor_types(count: int, existing: Counter | None = None) -> list[AnchorType]:
    """Allocate anchor types for `count` new links so the running total stays within 70/20/10.

    Exact match is a hard ceiling: it is never allowed to exceed 10% of all links.
    """
    existing = Counter(existing or {})
    plan: list[AnchorType] = []
    for _ in range(count):
        total = sum(existing.values()) + 1
        exact_cap = math.floor(total * ANCHOR_DISTRIBUTION["exact"])
        deficits = {}
        for t in AnchorType:
            if t is AnchorType.EXACT and existing[t] + 1 > exact_cap:
                continue
            deficits[t] = total * ANCHOR_DISTRIBUTION[t.value] - existing[t]
        choice = max(deficits, key=lambda t: (deficits[t], t is AnchorType.BRANDED))
        existing[choice] += 1
        plan.append(choice)
    return plan


def build_anchor_text(site: TargetWebsite, anchor_type: AnchorType, rng: random.Random) -> str:
    brand = site.brand_name or site.domain
    kw = rng.choice(site.keywords) if site.keywords else site.niche
    if anchor_type is AnchorType.BRANDED:
        return rng.choice([brand, site.domain, f"{brand} team"])
    if anchor_type is AnchorType.PARTIAL:
        if site.language == "ar":
            return rng.choice([f"حلول {kw}", f"دليل {kw} من {brand}", f"خدمات {kw}"])
        return rng.choice([f"{kw} solutions", f"{brand}'s {kw} guide", f"{kw} platform"])
    return kw


def plan_anchors(site: TargetWebsite, count: int, existing: Counter | None = None,
                 seed: int | None = None) -> list[AnchorPlan]:
    rng = random.Random(seed)
    return [AnchorPlan(build_anchor_text(site, t, rng), t) for t in plan_anchor_types(count, existing)]


# ---------------------------------------------------------------- validation

def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def keyword_density(text: str, keyword: str) -> float:
    words = word_count(text)
    if not words or not keyword:
        return 0.0
    hits = len(re.findall(re.escape(keyword.lower()), text.lower()))
    return hits * word_count(keyword) / words


def validate_article(article: Article, keywords: list[str]) -> list[str]:
    problems = []
    lo, hi = INTRO_WORD_RANGE
    intro_words = word_count(article.introduction)
    if not lo <= intro_words <= hi:
        problems.append(f"Introduction is {intro_words} words; expected {lo}-{hi}")
    if len(article.sections) < MIN_H2_SECTIONS:
        problems.append(f"Only {len(article.sections)} H2 sections; expected at least {MIN_H2_SECTIONS}")
    if not article.conclusion.strip():
        problems.append("Missing conclusion")
    if not article.cta.strip():
        problems.append("Missing call to action")
    full = article.to_markdown()
    links = full.count(f"]({article.link_url})")
    if links != 1:
        problems.append(f"Backlink appears {links} times; expected exactly once, in context")
    if f"[{article.anchor_text}]({article.link_url})" not in full:
        problems.append("Backlink does not use the planned anchor text")
    for kw in keywords:
        density = keyword_density(full, kw)
        if density > MAX_KEYWORD_DENSITY:
            problems.append(f"Keyword stuffing: '{kw}' density {density:.1%}")
    return problems


# ---------------------------------------------------------------- generation

class ArticleWriter(Protocol):
    def write(self, brief: "ArticleBrief") -> Article: ...


@dataclass
class ArticleBrief:
    site: TargetWebsite
    host: BacklinkOpportunity
    topic: str
    format: ArticleFormat
    anchor: AnchorPlan
    link_url: str

    @property
    def language(self) -> str:
        return self.host.language


ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "introduction": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"heading": {"type": "string"}, "body": {"type": "string"}},
                "required": ["heading", "body"],
                "additionalProperties": False,
            },
        },
        "conclusion": {"type": "string"},
        "cta": {"type": "string"},
    },
    "required": ["title", "introduction", "sections", "conclusion", "cta"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are an experienced industry writer producing editorial content for \
publication on a third-party website. The piece must stand on its own as genuinely useful to \
that site's readers; the client brand is mentioned only where it naturally helps the reader.

Requirements:
- Write entirely in the host site's language, matching its tone, audience, country and industry \
terminology. For Arabic, write natural Modern Standard Arabic suited to the stated country.
- Original writing only: no boilerplate, no filler, no keyword stuffing.
- Introduction of 100-150 words.
- At least four H2 sections (plain heading text, no '#'), each with concrete examples. Include \
statistics only when you are confident they are accurate and attribute them to their source; \
otherwise omit numbers rather than invent them.
- A conclusion and a short, natural call to action that is not a hard sell.
- Include the client link exactly once, in Markdown form [anchor](url), inside a section body \
where it genuinely supports the point being made. Use the anchor text exactly as given."""


def _brief_prompt(b: ArticleBrief) -> str:
    return json.dumps({
        "host_site": b.host.website,
        "host_country": b.host.country,
        "language": b.language,
        "article_format": b.format.value,
        "topic": b.topic,
        "niche": b.site.niche,
        "audience": b.site.audience,
        "client_brand": b.site.brand_name or b.site.domain,
        "client_services": b.site.services,
        "anchor_text": b.anchor.text,
        "link_url": b.link_url,
    }, ensure_ascii=False, indent=2)


class ClaudeArticleWriter:
    """Generates articles with the Claude API using structured JSON output."""

    def __init__(self, client=None, model: str = DEFAULT_MODEL):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.model = model

    def write(self, brief: ArticleBrief) -> Article:
        # Server-side fallbacks re-run a refused request on another model within the same call.
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Write the article for this brief:\n" + _brief_prompt(brief)}],
            output_config={"format": {"type": "json_schema", "schema": ARTICLE_SCHEMA}},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Article generation declined for topic {brief.topic!r}")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Article generation hit max_tokens before finishing")
        data = json.loads(next(b.text for b in response.content if b.type == "text"))
        return Article(
            title=data["title"],
            language=brief.language,
            format=brief.format,
            introduction=data["introduction"],
            sections=[ArticleSection(s["heading"], s["body"]) for s in data["sections"]],
            conclusion=data["conclusion"],
            cta=data["cta"],
            anchor_text=brief.anchor.text,
            anchor_type=brief.anchor.type,
            link_url=brief.link_url,
        )


def generate_article(writer: ArticleWriter, brief: ArticleBrief, max_attempts: int = 2) -> Article:
    """Write an article and re-generate if it fails structural/anti-spam validation."""
    problems: list[str] = []
    for _ in range(max_attempts):
        article = writer.write(brief)
        problems = validate_article(article, brief.site.keywords)
        if not problems:
            return article
    raise ValueError("Article failed validation: " + "; ".join(problems))
