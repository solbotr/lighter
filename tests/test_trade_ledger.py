import sqlite3

import pytest

from trade_ledger import TradeLedger, format_attribution_report


def entry(ledger, trade_id="t1", position_id="p1", side="BUY", source="good",
          entry_price=100.0, signal_price=100.0, size=10.0, published_at=1.0):
    ledger.record_entry(
        trade_id=trade_id, position_id=position_id, asset="ETH", side=side,
        source_id=source, publisher="wire", event_type="listing",
        catalyst_headline="headline", confidence=.9, published_at=published_at,
        ingested_at=2.0, decided_at=2.1, filled_at=3.0,
        entry_price=entry_price, signal_price=signal_price, size=size,
        notional_usd=entry_price * size, taker_fee_bps=10.0)


def rows(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con.execute("SELECT * FROM trade_ledger ORDER BY exit_at").fetchall()


def test_long_full_exit_calculates_pnl_and_fees(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = TradeLedger(str(path))
    entry(ledger)
    ledger.record_exit(position_id="p1", exit_price=102, exit_qty=10,
                       exit_kind="TP", exit_at=13, taker_fee_bps=10)
    exit_row = [r for r in rows(path) if r["exit_at"] is not None][0]
    assert exit_row["gross_pnl_usd"] == pytest.approx(20, abs=1e-6)
    assert exit_row["exit_fee_usd"] == pytest.approx(1.02, abs=1e-6)
    assert exit_row["net_pnl_usd"] == pytest.approx(20 - 1 - 1.02, abs=1e-6)
    assert exit_row["pnl_pct"] == pytest.approx(2, abs=1e-6)


def test_short_lower_exit_is_win(tmp_path):
    ledger = TradeLedger(str(tmp_path / "ledger.db"))
    entry(ledger, side="SELL")
    ledger.record_exit(position_id="p1", exit_price=98, exit_qty=10,
                       exit_kind="TP", exit_at=13, taker_fee_bps=0)
    report = ledger.attribution(0)
    assert report["totals"]["gross_pnl_usd"] == 20
    assert report["totals"]["win_rate_pct"] == 100


def test_partial_exits_are_separate_and_close_entry_last(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = TradeLedger(str(path))
    entry(ledger)
    ledger.record_exit(position_id="p1", exit_price=102, exit_qty=5,
                       exit_kind="TP1", exit_at=10, taker_fee_bps=10)
    assert [r for r in rows(path) if r["exit_at"] is None][0]["closed"] == 0
    ledger.record_exit(position_id="p1", exit_price=104, exit_qty=5,
                       exit_kind="TP2", exit_at=11, taker_fee_bps=10)
    all_rows = rows(path)
    assert len([r for r in all_rows if r["exit_at"] is not None]) == 2
    assert [r for r in all_rows if r["exit_at"] is None][0]["closed"] == 1
    # gross 10 + 20; entry fees .5+.5; exit fees .51+.52
    assert sum(r["net_pnl_usd"] for r in all_rows if r["exit_at"] is not None) == pytest.approx(27.97)


def test_attribution_ordering_and_prune_threshold(tmp_path):
    ledger = TradeLedger(str(tmp_path / "ledger.db"))
    entry(ledger, trade_id="winner", position_id="winner", source="winner")
    ledger.record_exit(position_id="winner", exit_price=110, exit_qty=10,
                       exit_kind="TP", exit_at=20, taker_fee_bps=0)
    for i in range(5):
        entry(ledger, trade_id=f"loser{i}", position_id=f"loser{i}", source="loser")
        ledger.record_exit(position_id=f"loser{i}", exit_price=99, exit_qty=10,
                           exit_kind="SL", exit_at=30 + i, taker_fee_bps=0)
    report = ledger.attribution(0)
    assert [x["key"] for x in report["by_source"]] == ["winner", "loser"]
    assert report["by_source"][0]["win_rate_pct"] == 100
    assert report["by_source"][1]["win_rate_pct"] == 0
    text = format_attribution_report(report, 24)
    assert "<code>loser</code>" in text and "❌ prune" in text
    assert text.split("<code>winner</code>", 1)[1].split("\n", 1)[0].find("❌ prune") == -1


def test_latency_null_and_signed_slippage(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = TradeLedger(str(path))
    entry(ledger, trade_id="long", position_id="long", entry_price=101,
          signal_price=100, published_at=None)
    entry(ledger, trade_id="short", position_id="short", side="SHORT",
          entry_price=99, signal_price=100)
    data = {r["trade_id"]: r for r in rows(path)}
    assert data["long"]["feed_latency_ms"] is None
    assert data["long"]["entry_slippage_bps"] == pytest.approx(100)
    assert data["short"]["entry_slippage_bps"] == pytest.approx(100)
