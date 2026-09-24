# AI SEO Backlink Agent

A white-hat, editorial-first SEO link building agent. It analyzes target
websites, researches competitor backlink profiles, scores link opportunities,
generates human-quality content, drives personalized outreach, and tracks
everything in a backlink database — all built around long-term organic
authority rather than spam or automated link schemes.

See [`SPEC.md`](SPEC.md) for the full system specification this project
implements.

## What it does

- **Website analysis** — niche, audience, country, language, keywords,
  competitors, and current backlink profile for a target site.
- **Competitor backlink research** — pluggable clients for Ahrefs, Semrush,
  and Google search-operator discovery, filtered to DR 70+ (DR 80+
  preferred), relevant, real-traffic, indexed, natural-profile sites.
- **Opportunity scoring** — a weighted 1-100 score
  (Authority 30% / Relevance 30% / Traffic 20% / Spam Risk 10% /
  Content Quality 10%); only score 80+ is recommended.
- **Content engine** — language-matched (Arabic/English, extensible)
  article generation with a fixed structure (intro, H2 sections, examples,
  stats, conclusion, natural CTA) and a 70/20/10 branded/partial/exact
  anchor-text mix.
- **Outreach system** — personalized emails plus Day 3 / Day 7 / Day 14
  follow-ups, never generic blasts.
- **Backlink tracking database** — SQLite store with the full column set
  from the spec (site, DR/DA, traffic, language, country, contact,
  opportunity type, status, article, published URL, anchor text, dates,
  link status).
- **Quality control** — a reject/accept checklist that filters out link
  farms, PBNs, spam networks, and automated directories before anything
  is tracked as accepted.
- **Monthly workflow & reporting** — find 500 → filter top 100 → outreach
  → content → track → report, driven by one orchestrator and summarized
  into a monthly SEO link building report.

## Project layout

```
seo_agent/
  config.py                  thresholds, scoring weights, anchor-text mix
  models.py                  dataclasses for the domain objects
  scoring.py                 opportunity scoring engine
  language.py                lightweight language detection
  website_analysis.py        target-site analysis + opportunity report
  competitor_research.py     pluggable Ahrefs/Semrush/Google-operator clients
  content_engine.py          article generation + anchor text planner
  outreach.py                outreach email + follow-up scheduler
  quality_control.py         accept/reject checklist
  database.py                SQLite backlink tracking store
  workflow.py                monthly workflow orchestrator
  reporting.py               monthly report builder
  cli.py                     command-line entry point

tests/                     pytest suite covering scoring, anchors, QC, DB
```

## Usage

```bash
pip install -r requirements.txt

# Score + quality-check a single prospect
python -m seo_agent.cli score-opportunity --dr 82 --traffic 400000 \
  --relevance 90 --content-quality 85 --spam-score 3

# Website analysis, opportunity report, strategy, topics, search footprints
python -m seo_agent.cli analyze --site examples/site.json --exports examples/exports

# Plan anchor texts that keep the 70/20/10 mix (pass existing counts to rebalance)
python -m seo_agent.cli plan-anchors --site examples/site.json --count 10 --exact 4

# Full monthly cycle: discover → shortlist → outreach → content → track → report
python -m seo_agent.cli run-monthly-workflow --site examples/site.json \
  --exports examples/exports --personalization examples/personalization.json \
  --out out/ [--write-content]

# Inspect the tracking database / regenerate a report
python -m seo_agent.cli list --db backlinks.db
python -m seo_agent.cli monthly-report --db backlinks.db --month 2026-09
```

### Inputs

- **Site config** (`examples/site.json`) — the target website's niche,
  audience, country, language, services, keywords, competitors, and current
  backlink profile.
- **Competitor exports** (`examples/exports/<competitor>.csv`) — referring
  domains exported from Ahrefs or Semrush. `AhrefsClient` / `SemrushClient`
  are stubs for direct API access; they read `AHREFS_API_KEY` /
  `SEMRUSH_API_KEY` and raise a clear error instead of returning fake data.
- **Personalization research** (`examples/personalization.json`) — per-site
  contact name, a real article on their site, the content idea, and the value
  proposition. Prospects without this research are skipped: the agent never
  sends generic emails.

### Content generation

`--write-content` generates articles for prospects marked `accepted`
with the Claude API (`claude-opus-5`, structured JSON output, server-side
refusal fallbacks enabled). Authenticate with `ANTHROPIC_API_KEY` or
`ant auth login`. Every article is validated before it's saved: the
introduction must be 100–150 words, there must be at least 3 H2 sections
plus a conclusion and a CTA, the link must appear exactly once with the
planned anchor, and keyword density is checked to catch stuffing. Articles
are written in the host site's language (Arabic or English).

### Status lifecycle

`prospect → contacted → accepted → published` (or `rejected`). Mark
replies and publications in the database (`BacklinkDatabase.update_status`,
`mark_published`). Monthly link checks record `live` / `nofollow` / `lost`
history, which the report uses for new and lost backlinks. Site DR/traffic
and keyword rankings are recorded with `record_site_metrics` and
`record_rankings`.

## Testing

```bash
pytest
```
