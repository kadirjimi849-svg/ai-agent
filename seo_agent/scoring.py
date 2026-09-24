from __future__ import annotations

import math

from .config import MAX_SPAM_SCORE, RECOMMEND_THRESHOLD, SCORING_WEIGHTS
from .models import BacklinkOpportunity


def authority_component(dr: int, da: int) -> float:
    return max(0.0, min(100.0, (dr + da) / 2))


def traffic_component(monthly_traffic: int) -> float:
    # Log scale: 1k visits ≈ 43, 100k ≈ 71, 1M ≈ 86, 10M+ = 100.
    if monthly_traffic <= 0:
        return 0.0
    return max(0.0, min(100.0, math.log10(monthly_traffic) / 7 * 100))


def spam_safety_component(spam_score: int) -> float:
    # Spam score is 0-100 where lower is better; invert so safer sites score higher.
    return max(0.0, 100.0 - spam_score * (100 / (MAX_SPAM_SCORE * 3)))


def score_opportunity(opp: BacklinkOpportunity) -> float:
    components = {
        "authority": authority_component(opp.dr, opp.da),
        "relevance": max(0.0, min(100.0, opp.relevance)),
        "traffic": traffic_component(opp.monthly_traffic),
        "spam_risk": spam_safety_component(opp.spam_score),
        "content_quality": max(0.0, min(100.0, opp.content_quality)),
    }
    total = sum(components[k] * w for k, w in SCORING_WEIGHTS.items())
    return round(max(1.0, min(100.0, total)), 1)


def is_recommended(opp: BacklinkOpportunity) -> bool:
    score = opp.score if opp.score is not None else score_opportunity(opp)
    return score >= RECOMMEND_THRESHOLD


def rank_opportunities(opps: list[BacklinkOpportunity]) -> list[BacklinkOpportunity]:
    for opp in opps:
        opp.score = score_opportunity(opp)
    return sorted(opps, key=lambda o: o.score, reverse=True)
