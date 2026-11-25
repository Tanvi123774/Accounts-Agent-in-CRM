
"""
Central configuration for Account Intelligence.

These values are PROVISIONAL. They are not an approved production
scoring policy. Do not activate the old draft database configuration.
"""

SCORING_VERSION = "provisional-0.2"

WEIGHTS = {
    "customer_engagement": 25,
    "relationship_strength": 20,
    "pipeline_momentum": 25,
    "commercial_relationship": 20,
    "follow_up_effectiveness": 10,
}

THRESHOLDS = {
    "Healthy": 70,
    "Needs Attention": 40,
    "At Risk": 0,
}

INACTIVITY_THRESHOLD_DAYS = 30

RECENCY_WINDOWS = {
    "very_recent_days": 7,
    "recent_days": 30,
    "moderate_days": 60,
    "old_days": 90,
}

RECENCY_SCORES = {
    "very_recent": 100,
    "recent": 80,
    "moderate": 60,
    "old": 35,
    "stale": 15,
}

def classify_health(score):
    if score is None:
        return "Not Assessed"

    if score >= THRESHOLDS["Healthy"]:
        return "Healthy"

    if score >= THRESHOLDS["Needs Attention"]:
        return "Needs Attention"

    return "At Risk"
