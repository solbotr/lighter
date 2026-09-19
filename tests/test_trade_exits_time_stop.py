import pytest

from trade_exits import policy_for, time_stop_seconds


def _clear_hold_overrides(monkeypatch):
    monkeypatch.delenv("NEWS_MAX_HOLD_DAYS", raising=False)
    monkeypatch.delenv("NEWS_MAX_HOLD_MINUTES", raising=False)
    monkeypatch.delenv("NEWS_STOP_LOSS_PCT", raising=False)
    monkeypatch.delenv("NEWS_TRAIL_ARM_PCT", raising=False)
    monkeypatch.delenv("NEWS_TRAIL_GAP_PCT", raising=False)


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("Routine project update", 3600.0),
        ("Binance will list XYZ", 14400.0),
        ("Fed cuts interest rate", 5400.0),
        ("X partners with Y", 7200.0),
    ],
)
def test_catalyst_default_time_stops(monkeypatch, headline, expected):
    _clear_hold_overrides(monkeypatch)
    assert policy_for("ETH", news_headline=headline).max_hold_seconds == expected


def test_tier1_precedes_partnership(monkeypatch):
    _clear_hold_overrides(monkeypatch)
    headline = "Binance will list XYZ after partnership announcement"
    assert policy_for("ETH", news_headline=headline).max_hold_seconds == 14400.0


def test_minutes_override_applies_to_all_classes(monkeypatch):
    _clear_hold_overrides(monkeypatch)
    monkeypatch.setenv("NEWS_MAX_HOLD_MINUTES", "15")
    for headline in ("Routine update", "Binance will list XYZ", "Fed cuts rates", "partnership"):
        assert policy_for("ETH", news_headline=headline).max_hold_seconds == 900.0


def test_legacy_days_override(monkeypatch):
    _clear_hold_overrides(monkeypatch)
    monkeypatch.setenv("NEWS_MAX_HOLD_DAYS", "2")
    assert policy_for("ETH", news_headline="Binance will list XYZ").max_hold_seconds == 172800.0


@pytest.mark.parametrize(
    ("headline", "expected"),
    [
        ("Routine project update", (2.00, 0.85, 2.00, 1.00)),
        ("Binance will list XYZ", (6.00, 2.20, 4.00, 1.80)),
        ("Fed cuts interest rate", (2.00, 0.85, 2.00, 1.00)),
        ("X partners with Y", (4.00, 1.50, 2.50, 1.20)),
    ],
)
def test_eth_tp_sl_and_trail_regression(monkeypatch, headline, expected):
    _clear_hold_overrides(monkeypatch)
    policy = policy_for("ETH", news_headline=headline)
    # Expected values captured from the pre-refactor implementation.
    assert (policy.tp_pct, policy.sl_pct, policy.trail_arm_pct, policy.trail_gap_pct) == expected


def test_time_stop_helper_for_fda_approval(monkeypatch):
    _clear_hold_overrides(monkeypatch)
    assert time_stop_seconds("ETH", news_headline="FDA approves ...") == 14400.0
