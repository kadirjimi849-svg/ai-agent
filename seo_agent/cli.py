from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from .competitor_research import CsvExportSource, search_operator_queries
from .content_engine import plan_anchors
from .database import BacklinkDatabase
from .models import AnchorType, BacklinkOpportunity, OutreachStatus, TargetWebsite
from .outreach import OutreachContext
from .quality_control import check_opportunity
from .reporting import build_monthly_report
from .scoring import is_recommended, score_opportunity
from .website_analysis import BacklinkProfile, analyze_website
from .workflow import MonthlyWorkflow


def _load_site(path: str) -> tuple[TargetWebsite, BacklinkProfile]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    profile = BacklinkProfile(**data.pop("backlink_profile", {}))
    return TargetWebsite(**data), profile


def cmd_score(args) -> int:
    opp = BacklinkOpportunity(
        website=args.website, url=f"https://{args.website}", dr=args.dr, da=args.da or args.dr,
        monthly_traffic=args.traffic, spam_score=args.spam_score, relevance=args.relevance,
        content_quality=args.content_quality,
    )
    opp.score = score_opportunity(opp)
    qc = check_opportunity(opp)
    print(f"Score: {opp.score}/100 — {'RECOMMENDED' if is_recommended(opp) else 'not recommended'}")
    print(f"Quality control: {'PASS' if qc.accepted else 'REJECT'}")
    for f in qc.failures:
        print(f"  ✗ {f}")
    for w in qc.warnings:
        print(f"  ! {w}")
    return 0


def cmd_analyze(args) -> int:
    site, profile = _load_site(args.site)
    comps = []
    if args.exports:
        from .competitor_research import collect_competitor_backlinks
        comps = collect_competitor_backlinks(site, [CsvExportSource(args.exports)])
    print(analyze_website(site, profile, comps).to_markdown())
    print("\n## Search operator footprints")
    for q in search_operator_queries(site):
        print(f"- {q}")
    return 0


def cmd_anchors(args) -> int:
    site, _ = _load_site(args.site)
    existing = Counter({AnchorType.BRANDED: args.branded, AnchorType.PARTIAL: args.partial,
                        AnchorType.EXACT: args.exact})
    for a in plan_anchors(site, args.count, existing):
        print(f"{a.type.value:8} {a.text}")
    return 0


def _personalizer(path: str | None):
    if not path:
        return None
    contexts = json.loads(Path(path).read_text(encoding="utf-8"))

    def personalize(opp: BacklinkOpportunity):
        c = contexts.get(opp.website)
        return OutreachContext(host=opp, **c) if c else None

    return personalize


def cmd_run(args) -> int:
    site, _ = _load_site(args.site)
    db = BacklinkDatabase(args.db)
    writer = None
    if args.write_content:
        from .content_engine import ClaudeArticleWriter
        writer = ClaudeArticleWriter()
    wf = MonthlyWorkflow(site, db, sources=[CsvExportSource(args.exports)], writer=writer,
                         personalizer=_personalizer(args.personalization))
    month = args.month or date.today().strftime("%Y-%m")
    result = wf.run(month)
    print(f"Discovered {result.discovered} prospects; {result.rejected_qc} rejected by QC; "
          f"{result.below_threshold} below score 80; shortlisted {len(result.shortlist)}.")
    print(f"Outreach sequences created: {len(result.outreach)}; skipped: {len(result.skipped_outreach)}")
    for s in result.skipped_outreach:
        print(f"  - {s}")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for website, emails in result.outreach.items():
            text = "\n\n---\n\n".join(f"[send {e.send_on}] To: {e.to}\nSubject: {e.subject}\n\n{e.body}"
                                      for e in emails)
            (out / f"outreach_{website}.txt").write_text(text, encoding="utf-8")
        for website, article in result.articles.items():
            (out / f"article_{website}.md").write_text(article.to_markdown(), encoding="utf-8")
        (out / f"report_{month}.md").write_text(result.report.to_markdown(), encoding="utf-8")
        print(f"Wrote outputs to {out}/")
    else:
        print()
        print(result.report.to_markdown())
    return 0


def cmd_report(args) -> int:
    db = BacklinkDatabase(args.db)
    print(build_monthly_report(db, args.month or date.today().strftime("%Y-%m")).to_markdown())
    return 0


def cmd_list(args) -> int:
    db = BacklinkDatabase(args.db)
    status = OutreachStatus(args.status) if args.status else None
    for r in db.all(status):
        print(f"{r.id:4} {r.website:30} DR{r.dr:3} {r.status.value:10} {r.link_status.value:8} "
              f"{r.anchor_text or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="seo-agent", description="White-hat SEO backlink agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score-opportunity", help="Score and QC a single prospect")
    s.add_argument("--website", default="example.com")
    s.add_argument("--dr", type=int, required=True)
    s.add_argument("--da", type=int)
    s.add_argument("--traffic", type=int, required=True, help="Monthly organic visits")
    s.add_argument("--spam-score", type=int, default=0)
    s.add_argument("--relevance", type=float, required=True, help="0-100")
    s.add_argument("--content-quality", type=float, required=True, help="0-100")
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("analyze", help="Website analysis + opportunity report")
    s.add_argument("--site", required=True, help="Target site JSON config")
    s.add_argument("--exports", help="Directory of competitor referring-domain CSV exports")
    s.set_defaults(func=cmd_analyze)

    s = sub.add_parser("plan-anchors", help="Plan anchor texts keeping the 70/20/10 mix")
    s.add_argument("--site", required=True)
    s.add_argument("--count", type=int, default=10)
    s.add_argument("--branded", type=int, default=0, help="Existing branded anchors")
    s.add_argument("--partial", type=int, default=0)
    s.add_argument("--exact", type=int, default=0)
    s.set_defaults(func=cmd_anchors)

    s = sub.add_parser("run-monthly-workflow", help="Discover → shortlist → outreach → content → track → report")
    s.add_argument("--site", required=True)
    s.add_argument("--exports", required=True)
    s.add_argument("--db", default="backlinks.db")
    s.add_argument("--personalization", help="JSON of per-website outreach research")
    s.add_argument("--write-content", action="store_true", help="Generate articles with the Claude API")
    s.add_argument("--month", help="YYYY-MM")
    s.add_argument("--out", help="Directory for outreach, article and report files")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("monthly-report", help="Monthly SEO link building report")
    s.add_argument("--db", default="backlinks.db")
    s.add_argument("--month", help="YYYY-MM")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("list", help="List tracked backlinks")
    s.add_argument("--db", default="backlinks.db")
    s.add_argument("--status", choices=[x.value for x in OutreachStatus])
    s.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
