from collections import Counter
from datetime import date
from types import SimpleNamespace

import json
import pytest

from seo_agent.content_engine import (ClaudeArticleWriter, ArticleBrief, AnchorPlan, generate_article,
                                      plan_anchor_types, validate_article)
from seo_agent.database import BacklinkDatabase
from seo_agent.language import detect_language
from seo_agent.models import (AnchorType, Article, ArticleFormat, ArticleSection, BacklinkOpportunity,
                              BacklinkRecord, LinkStatus, OpportunityType, OutreachStatus, TargetWebsite)
from seo_agent.outreach import MissingPersonalization, OutreachContext, build_sequence, due_emails
from seo_agent.quality_control import check_opportunity
from seo_agent.reporting import build_monthly_report, previous_month
from seo_agent.scoring import is_recommended, score_opportunity
from seo_agent.workflow import MonthlyWorkflow

SITE = TargetWebsite(domain="acmecrm.com", brand_name="AcmeCRM", niche="CRM software",
                     keywords=["CRM software", "sales pipeline"], competitors=["hubspot.com"])


def opp(**kw):
    base = dict(website="host.example", url="https://host.example", dr=85, da=80, monthly_traffic=500_000,
                spam_score=2, relevance=90, content_quality=90, contact_email="ed@host.example")
    base.update(kw)
    return BacklinkOpportunity(**base)


# ---------------------------------------------------------------- scoring / QC

def test_high_quality_opportunity_is_recommended():
    o = opp()
    assert 80 <= score_opportunity(o) <= 100
    assert is_recommended(o)


def test_irrelevant_high_authority_site_not_recommended():
    assert not is_recommended(opp(relevance=20))


def test_score_bounds():
    assert score_opportunity(opp(dr=0, da=0, monthly_traffic=0, spam_score=100, relevance=0,
                                 content_quality=0)) == 1
    assert score_opportunity(opp(dr=100, da=100, monthly_traffic=10**8, spam_score=0, relevance=100,
                                 content_quality=100)) == 100


@pytest.mark.parametrize("flag", ["link_farm", "pbn", "automated_directory", "spam_site"])
def test_qc_rejects_spam_patterns(flag):
    result = check_opportunity(opp(flags={flag}))
    assert not result.accepted


def test_qc_rejects_low_dr_and_unindexed():
    assert not check_opportunity(opp(dr=60)).accepted
    assert not check_opportunity(opp(indexed=False)).accepted
    assert check_opportunity(opp()).accepted


# ---------------------------------------------------------------- anchors

@pytest.mark.parametrize("n", [1, 7, 10, 23, 100])
def test_anchor_distribution(n):
    counts = Counter(plan_anchor_types(n))
    assert counts[AnchorType.EXACT] <= int(n * 0.10)
    assert counts[AnchorType.BRANDED] >= int(n * 0.70) - 1
    assert sum(counts.values()) == n


def test_anchor_plan_compensates_for_overoptimized_profile():
    existing = Counter({AnchorType.EXACT: 5, AnchorType.BRANDED: 5})
    new = plan_anchor_types(10, existing)
    assert AnchorType.EXACT not in new


# ---------------------------------------------------------------- language

def test_language_detection():
    assert detect_language("أفضل برامج إدارة علاقات العملاء") == "ar"
    assert detect_language("Best CRM software for teams") == "en"
    assert detect_language('<html lang="ar"><body>hello</body></html>') == "ar"


# ---------------------------------------------------------------- content

def make_article(intro_words=120, sections=4, link_times=1):
    link = "[AcmeCRM](https://acmecrm.com/)"
    secs = [ArticleSection(f"Heading {i}", "Some helpful body text with examples. " * 10) for i in range(sections)]
    if link_times:
        secs[0].body += " " + " ".join([f"See {link}."] * link_times)
    return Article(title="T", language="en", format=ArticleFormat.GUEST_POST,
                   introduction=" ".join(["word"] * intro_words), sections=secs,
                   conclusion="Wrap up.", cta="Try it.", anchor_text="AcmeCRM",
                   anchor_type=AnchorType.BRANDED, link_url="https://acmecrm.com/")


def test_valid_article_passes():
    assert validate_article(make_article(), SITE.keywords) == []


def test_article_validation_catches_problems():
    assert any("Introduction" in p for p in validate_article(make_article(intro_words=40), []))
    assert any("H2" in p for p in validate_article(make_article(sections=2), []))
    assert any("exactly once" in p for p in validate_article(make_article(link_times=2), []))
    stuffed = make_article()
    stuffed.sections[1].body = "CRM software " * 80
    assert any("stuffing" in p for p in validate_article(stuffed, SITE.keywords))


class FakeClient:
    def __init__(self, payload):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.payload = payload

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.payload))])


def test_claude_writer_builds_article_from_structured_output():
    a = make_article()
    payload = {"title": "Guide", "introduction": a.introduction,
               "sections": [{"heading": s.heading, "body": s.body} for s in a.sections],
               "conclusion": a.conclusion, "cta": a.cta}
    client = FakeClient(payload)
    brief = ArticleBrief(SITE, opp(language="en"), "Pipelines", ArticleFormat.GUEST_POST,
                         AnchorPlan("AcmeCRM", AnchorType.BRANDED), "https://acmecrm.com/")
    article = generate_article(ClaudeArticleWriter(client=client), brief)
    assert article.title == "Guide"
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"


# ---------------------------------------------------------------- outreach

def ctx(**kw):
    base = dict(host=opp(), contact_name="Dana", sender_name="Sam", sender_role="Editor",
                referenced_article_title="Sales Process 101", referenced_article_url="https://host.example/a",
                content_idea="Pipeline audit framework", value_proposition="Actionable checklist")
    base.update(kw)
    return OutreachContext(**base)


def test_outreach_sequence_has_followups_on_day_3_7_14():
    seq = build_sequence(ctx(), SITE, start=date(2026, 1, 1))
    assert [(e.send_on - date(2026, 1, 1)).days for e in seq] == [0, 3, 7, 14]
    first = seq[0].body
    for piece in ("host.example", "Sales Process 101", "Sam", "Pipeline audit framework", "Actionable checklist"):
        assert piece in first


def test_arabic_host_gets_arabic_email():
    seq = build_sequence(ctx(host=opp(language="ar")), SITE)
    assert detect_language(seq[0].body) == "ar"


def test_generic_email_refused():
    with pytest.raises(MissingPersonalization):
        build_sequence(ctx(referenced_article_title=""), SITE)


def test_followups_stop_after_reply():
    seq = build_sequence(ctx(), SITE, start=date(2026, 1, 1))
    assert due_emails(seq, date(2026, 1, 4), replied=False) == [seq[1]]
    assert due_emails(seq, date(2026, 1, 4), replied=True) == []


# ---------------------------------------------------------------- database / report

def record(**kw):
    base = dict(website="host.example", url="https://host.example", dr=85, da=80, traffic=500_000,
                language="en", country="US", contact_email="ed@host.example",
                opportunity_type=OpportunityType.GUEST_POST)
    base.update(kw)
    return BacklinkRecord(**base)


def test_database_roundtrip_and_upsert(tmp_path):
    db = BacklinkDatabase(tmp_path / "b.db")
    i = db.upsert(record())
    assert db.upsert(record(dr=86)) == i
    assert db.get(i).dr == 86
    db.mark_published(i, "https://host.example/post", "Guide", "AcmeCRM")
    rec = db.get(i)
    assert rec.status is OutreachStatus.PUBLISHED and rec.anchor_text == "AcmeCRM"


def test_monthly_report_new_and_lost(tmp_path):
    db = BacklinkDatabase(tmp_path / "b.db")
    a = db.upsert(record(website="a.example", url="https://a.example"))
    b = db.upsert(record(website="b.example", url="https://b.example"))
    db.record_link_check(b, LinkStatus.LIVE, date(2026, 1, 10))
    db.record_link_check(a, LinkStatus.LIVE, date(2026, 2, 3))
    db.record_link_check(b, LinkStatus.LIVE, date(2026, 2, 3))
    db.record_link_check(b, LinkStatus.LOST, date(2026, 2, 20))
    db.record_site_metrics("2026-01", 40, 10_000)
    db.record_site_metrics("2026-02", 43, 12_500)
    db.record_rankings("2026-01", {"CRM software": 18})
    db.record_rankings("2026-02", {"CRM software": 11, "sales pipeline": 25})

    report = build_monthly_report(db, "2026-02")
    assert [r.website for r in report.new_backlinks] == ["a.example"]
    assert [r.website for r in report.lost_backlinks] == ["b.example"]
    assert report.dr == (40, 43)
    md = report.to_markdown()
    assert "+3" in md and "#18 → #11" in md and "new at #25" in md


def test_previous_month_wraps_year():
    assert previous_month("2026-01") == "2025-12"
    assert previous_month("2026-03") == "2026-02"


# ---------------------------------------------------------------- workflow

class ListSource:
    def __init__(self, opps):
        self.opps = opps

    def referring_domains(self, competitor):
        return self.opps


def test_monthly_workflow_end_to_end(tmp_path):
    db = BacklinkDatabase(tmp_path / "b.db")
    prospects = [
        opp(website="good.example", url="https://good.example"),
        opp(website="farm.example", url="https://farm.example", flags={"link_farm"}),
        opp(website="weak.example", url="https://weak.example", dr=50),
        opp(website="meh.example", url="https://meh.example", relevance=62, content_quality=60,
            monthly_traffic=6_000),
    ]
    wf = MonthlyWorkflow(SITE, db, sources=[ListSource(prospects)],
                         personalizer=lambda o: ctx(host=o) if o.website == "good.example" else None,
                         link_checker=lambda rec, site: LinkStatus.LIVE)
    result = wf.run("2026-02", today=date(2026, 2, 5))
    assert result.discovered == 3  # sub-DR70 dropped at collection
    assert result.rejected_qc == 1
    assert [o.website for o in result.shortlist] == ["good.example"]
    assert "good.example" in result.outreach
    assert db.all()[0].status is OutreachStatus.CONTACTED
