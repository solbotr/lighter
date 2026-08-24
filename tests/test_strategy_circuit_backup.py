import asyncio
import pytest
import time
from strategy_circuit_backup import (
    StrategyCircuitBackupManager,
    StrategyHealthStatus,
    global_strategy_circuit_backup,
)


def test_strategy_circuit_backup_sync_execution():
    mgr = StrategyCircuitBackupManager(error_threshold_for_backup=2, auto_heal_cooldown_sec=1.0)

    def buggy_strategy(x):
        if x < 0:
            raise ValueError("Negative value not allowed")
        return x * 2

    def safe_fallback(x):
        return abs(x)

    # 1. Normal execution
    res = mgr.safe_execute("test_strat", buggy_strategy, safe_fallback, 5)
    assert res == 10
    assert mgr.strategy_registry["test_strat"].is_healthy is True

    # 2. First failure -> triggers safe fallback
    res = mgr.safe_execute("test_strat", buggy_strategy, safe_fallback, -5)
    assert res == 5
    assert mgr.strategy_registry["test_strat"].consecutive_errors == 1

    # 3. Second failure -> activates fallback mode
    res = mgr.safe_execute("test_strat", buggy_strategy, safe_fallback, -10)
    assert res == 10
    assert mgr.strategy_registry["test_strat"].fallback_active is True
    assert mgr.strategy_registry["test_strat"].is_healthy is False

    # 4. Telemetry
    telem = mgr.get_fleet_telemetry()
    assert telem["total_strategies"] == 1
    assert telem["fallback_active_strategies"] == 1


@pytest.mark.asyncio
async def test_strategy_circuit_backup_async_execution():
    mgr = StrategyCircuitBackupManager(error_threshold_for_backup=2, auto_heal_cooldown_sec=0.2)

    async def async_buggy(x):
        if x == 0:
            raise ZeroDivisionError("division by zero")
        return 100 / x

    async def async_fallback(x):
        return 1.0

    # Normal async
    res = await mgr.async_safe_execute("async_strat", async_buggy, async_fallback, 10)
    assert res == 10.0

    # Failures
    res1 = await mgr.async_safe_execute("async_strat", async_buggy, async_fallback, 0)
    assert res1 == 1.0
    res2 = await mgr.async_safe_execute("async_strat", async_buggy, async_fallback, 0)
    assert res2 == 1.0
    assert mgr.strategy_registry["async_strat"].fallback_active is True

    # Auto-heal test after cooldown
    await asyncio.sleep(0.3)
    res3 = await mgr.async_safe_execute("async_strat", async_buggy, async_fallback, 5)
    assert res3 == 20.0
    assert mgr.strategy_registry["async_strat"].fallback_active is False
    assert mgr.strategy_registry["async_strat"].is_healthy is True
