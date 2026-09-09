"""SQLite-backed realized-PnL attribution for news-driven trades."""

import html
import sqlite3
from typing import Any, Dict


_COLUMNS = (
    "trade_id, position_id, asset, side, source_id, publisher, event_type, "
    "catalyst_headline, confidence, published_at, ingested_at, decided_at, "
    "filled_at, feed_latency_ms, decision_latency_ms, entry_price, signal_price, "
    "entry_slippage_bps, size, notional_usd, entry_fee_usd, exit_price, exit_qty, "
    "exit_fee_usd, exit_kind, exit_at, hold_seconds, gross_pnl_usd, net_pnl_usd, "
    "pnl_pct, closed"
).split(", ")


class TradeLedger:
    """Persist entries and one immutable child row for every exit event.

    Partial exits are represented by separate closed rows copied from the entry.
    The original entry is marked closed only after cumulative exit quantity reaches
    99.9% of its original size.  This preserves an auditable exit-event history.
    In speed mode an entry price may be the signal price while confirmation is
    asynchronous, so measured slippage is an upper-bound estimate.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS trade_ledger (
                trade_id TEXT PRIMARY KEY, position_id TEXT, asset TEXT, side TEXT,
                source_id TEXT, publisher TEXT, event_type TEXT, catalyst_headline TEXT,
                confidence REAL, published_at REAL, ingested_at REAL, decided_at REAL,
                filled_at REAL, feed_latency_ms REAL, decision_latency_ms REAL,
                entry_price REAL, signal_price REAL, entry_slippage_bps REAL, size REAL,
                notional_usd REAL, entry_fee_usd REAL, exit_price REAL, exit_qty REAL,
                exit_fee_usd REAL, exit_kind TEXT, exit_at REAL, hold_seconds REAL,
                gross_pnl_usd REAL, net_pnl_usd REAL, pnl_pct REAL,
                closed INTEGER DEFAULT 0
            )""")

    def record_entry(self, *, trade_id, position_id, asset, side, source_id,
                     publisher, event_type, catalyst_headline, confidence,
                     published_at, ingested_at, decided_at, filled_at, entry_price,
                     signal_price, size, notional_usd, taker_fee_bps):
        feed_ms = (ingested_at - published_at) * 1000 if published_at else None
        decision_ms = (filled_at - ingested_at) * 1000
        direction = 1 if self._is_long(side) else -1
        slippage = direction * (entry_price - signal_price) / signal_price * 1e4 if signal_price else None
        fee = notional_usd * taker_fee_bps / 1e4
        values = [trade_id, position_id, asset, side, source_id, publisher,
                  event_type, catalyst_headline, confidence, published_at,
                  ingested_at, decided_at, filled_at, feed_ms, decision_ms,
                  entry_price, signal_price, slippage, size, notional_usd, fee]
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT OR REPLACE INTO trade_ledger (" + ",".join(_COLUMNS[:21]) +
                ") VALUES (" + ",".join("?" * 21) + ")", values)

    def record_exit(self, *, position_id, exit_price, exit_qty, exit_kind,
                    exit_at, taker_fee_bps):
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            entry = db.execute(
                "SELECT * FROM trade_ledger WHERE position_id=? AND exit_at IS NULL "
                "ORDER BY filled_at LIMIT 1", (position_id,)).fetchone()
            if entry is None:
                return
            qty = float(exit_qty)
            gross = ((exit_price - entry["entry_price"]) * qty
                     if self._is_long(entry["side"])
                     else (entry["entry_price"] - exit_price) * qty)
            exit_fee = exit_price * qty * taker_fee_bps / 1e4
            allocated_entry_fee = (entry["entry_fee_usd"] or 0) * qty / entry["size"]
            net = gross - allocated_entry_fee - exit_fee
            direction = 1 if self._is_long(entry["side"]) else -1
            pnl_pct = direction * (exit_price - entry["entry_price"]) / entry["entry_price"] * 100
            trade_id = f"{position_id}:{exit_kind}:{int(exit_at * 1000)}"
            values = [entry[c] for c in _COLUMNS]
            updates = {
                "trade_id": trade_id, "exit_price": exit_price, "exit_qty": qty,
                "exit_fee_usd": exit_fee, "exit_kind": exit_kind, "exit_at": exit_at,
                "hold_seconds": exit_at - entry["filled_at"], "gross_pnl_usd": gross,
                "net_pnl_usd": net, "pnl_pct": pnl_pct, "closed": 1,
            }
            values = [updates.get(c, values[i]) for i, c in enumerate(_COLUMNS)]
            db.execute("INSERT OR REPLACE INTO trade_ledger (" + ",".join(_COLUMNS) +
                       ") VALUES (" + ",".join("?" * len(_COLUMNS)) + ")", values)
            exited = db.execute(
                "SELECT COALESCE(SUM(exit_qty),0) FROM trade_ledger "
                "WHERE position_id=? AND exit_at IS NOT NULL", (position_id,)).fetchone()[0]
            if exited >= 0.999 * entry["size"]:
                db.execute("UPDATE trade_ledger SET closed=1 WHERE trade_id=?", (entry["trade_id"],))

    def attribution(self, since_ts: float) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM trade_ledger WHERE closed=1 AND exit_at>=?", (since_ts,)).fetchall()

        def grouped(field):
            groups = {}
            for row in rows:
                groups.setdefault(row[field] or "unknown", []).append(row)
            result = []
            for key, items in groups.items():
                trades = len(items)
                wins = sum((r["net_pnl_usd"] or 0) > 0 for r in items)
                gross = sum(r["gross_pnl_usd"] or 0 for r in items)
                net = sum(r["net_pnl_usd"] or 0 for r in items)
                fees = sum((r["entry_fee_usd"] or 0) * (r["exit_qty"] or 0) / (r["size"] or 1)
                           + (r["exit_fee_usd"] or 0) for r in items)
                latencies = [r["feed_latency_ms"] for r in items if r["feed_latency_ms"] is not None]
                holds = [r["hold_seconds"] for r in items if r["hold_seconds"] is not None]
                result.append({"key": key, "trades": trades, "wins": wins,
                    "win_rate_pct": wins / trades * 100, "gross_pnl_usd": gross,
                    "net_pnl_usd": net, "fees_usd": fees,
                    "avg_feed_latency_ms": sum(latencies) / len(latencies) if latencies else None,
                    "avg_hold_seconds": sum(holds) / len(holds) if holds else None,
                    "expectancy_usd": net / trades})
            return sorted(result, key=lambda x: x["net_pnl_usd"], reverse=True)

        trades = len(rows)
        wins = sum((r["net_pnl_usd"] or 0) > 0 for r in rows)
        gross = sum(r["gross_pnl_usd"] or 0 for r in rows)
        net = sum(r["net_pnl_usd"] or 0 for r in rows)
        fees = sum((r["entry_fee_usd"] or 0) * (r["exit_qty"] or 0) / (r["size"] or 1)
                   + (r["exit_fee_usd"] or 0) for r in rows)
        return {"by_source": grouped("source_id"), "by_event_type": grouped("event_type"),
                "by_asset": grouped("asset"), "totals": {"trades": trades,
                "net_pnl_usd": net, "gross_pnl_usd": gross, "fees_usd": fees,
                "win_rate_pct": wins / trades * 100 if trades else 0.0}}

    @staticmethod
    def _is_long(side):
        return str(side).upper().startswith(("BUY", "LONG"))


def format_attribution_report(report: dict, hours: float) -> str:
    """Format compact attribution as Telegram-compatible HTML."""
    totals = report["totals"]
    lines = [f"<b>News Attribution ({hours:g}h)</b>",
             f"Total <code>{totals['trades']}</code> | Net <code>${totals['net_pnl_usd']:+.2f}</code> | "
             f"Gross <code>${totals['gross_pnl_usd']:+.2f}</code> | Fees <code>${totals['fees_usd']:.2f}</code> | "
             f"WR <code>{totals['win_rate_pct']:.1f}%</code>"]

    def line(item, latency=False):
        prune = " ❌ prune" if item["expectancy_usd"] < 0 and item["trades"] >= 5 else ""
        latency_text = (f" | {item['avg_feed_latency_ms']:.0f}ms"
                        if latency and item["avg_feed_latency_ms"] is not None else "")
        return (f"• <code>{html.escape(str(item['key']))}</code> ${item['net_pnl_usd']:+.2f} | "
                f"{item['win_rate_pct']:.0f}% | n={item['trades']}{latency_text}{prune}")

    sources = report["by_source"]
    selected = sources if len(sources) <= 10 else sources[:5] + sources[-5:]
    lines.extend(["<b>Sources (top/bottom)</b>"] + [line(x, True) for x in selected])
    lines.extend(["<b>Event types</b>"] + [line(x) for x in report["by_event_type"]])
    lines.extend(["<b>Assets (top 5)</b>"] + [line(x) for x in report["by_asset"][:5]])
    return "\n".join(lines)
