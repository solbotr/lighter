from datetime import datetime, timedelta, timezone

from lighter.news import NewsEngine, NewsEvent


def test_news_engine_rejects_rumor():
    event = NewsEvent("trusted", "Rumor: protocol launches", datetime.now(timezone.utc), source_score=0.95, metadata={"rumor": "true"})
    assessment = NewsEngine().assess(event)
    assert assessment is None or not assessment.tradable


def test_news_engine_dedupes():
    now = datetime.now(timezone.utc)
    event = NewsEvent("trusted", "Protocol approved for launch", now, source_score=0.95)
    engine = NewsEngine()
    assert engine.assess(event) is not None
    assert engine.assess(event) is None


def test_stale_event_rejected():
    event = NewsEvent("trusted", "Protocol approved for launch", datetime.now(timezone.utc) - timedelta(seconds=500), source_score=1.0)
    assert NewsEngine(max_age_seconds=120).assess(event) is None
