MIN_DR = 70
PREFERRED_DR = 80
MIN_DA = 70
MAX_SPAM_SCORE = 10
MIN_MONTHLY_TRAFFIC = 5_000

SCORING_WEIGHTS = {
    "authority": 0.30,
    "relevance": 0.30,
    "traffic": 0.20,
    "spam_risk": 0.10,
    "content_quality": 0.10,
}
RECOMMEND_THRESHOLD = 80

ANCHOR_DISTRIBUTION = {
    "branded": 0.70,
    "partial": 0.20,
    "exact": 0.10,
}

FOLLOW_UP_DAYS = (3, 7, 14)

MONTHLY_DISCOVERY_TARGET = 500
MONTHLY_SHORTLIST_SIZE = 100

INTRO_WORD_RANGE = (100, 150)

SUPPORTED_LANGUAGES = ("en", "ar")
