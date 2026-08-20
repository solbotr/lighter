from pathlib import Path

import pytest

from lighter_trader.execution.controls import KillSwitch
from lighter_trader.execution.live_readonly import LighterReadOnlyClient


def test_sdk_namespace_is_not_shadowed():
    import lighter
    import lighter_trader

    assert "site-packages" in lighter.__file__
    assert "src" in lighter_trader.__file__
    assert hasattr(lighter.SignerClient, "create_market_order")


def test_kill_switch_persists_and_requires_approval(tmp_path: Path):
    switch = KillSwitch(tmp_path / "kill.json")
    assert not switch.state().active
    switch.activate("operator emergency")
    assert switch.state().active
    with pytest.raises(ValueError):
        switch.clear("")
    switch.clear("approved-by-operator")
    assert not switch.state().active


def test_private_order_reads_fail_closed_without_auth_token():
    client = LighterReadOnlyClient("https://mainnet.zklighter.elliot.ai", account_index=1)
    client._api_client = object()
    client._orders = object()
    with pytest.raises(RuntimeError, match="auth session"):
        import asyncio
        asyncio.run(client.open_orders())
