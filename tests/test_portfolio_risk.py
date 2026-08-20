from lighter_trader.risk.portfolio import PortfolioLimits, check_portfolio


def test_portfolio_rejects_excessive_asset_concentration():
    result = check_portfolio(0, 0, 50, 1000, 100, 75, PortfolioLimits(max_asset_notional=100))
    assert not result.approved
    assert "asset_concentration_limit" in result.reasons


def test_portfolio_allows_safe_trade():
    result = check_portfolio(0, 0, 50, 1000, 100, 0, PortfolioLimits())
    assert result.approved
    assert result.allowed_notional >= 50
