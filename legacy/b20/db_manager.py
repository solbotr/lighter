#!/usr/bin/env python3
"""
Database Manager for B20 Bot
============================
SQLite database schema and management for:
- Trade history (buys, sells, results)
- Pool tracking
- PnL calculations
- Backtest data
- Token safety scores
- Performance analytics
"""

import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple


class DBManager:
    """Thread-safe SQLite database manager for the B20 bot."""

    def __init__(self, db_path: str = "b20_bot.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Get a new database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initialize database schema."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Pools table - track all detected pools
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pools (
                pool_address TEXT PRIMARY KEY,
                token_address TEXT NOT NULL,
                token_name TEXT,
                token_symbol TEXT,
                fee_tier INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                liquidity_eth REAL,
                safety_score INTEGER,
                holder_dist_top10 REAL,
                has_honeypot BOOLEAN DEFAULT 0,
                blacklisted BOOLEAN DEFAULT 0,
                notes TEXT
            )
        """)

        # Trades table - all buy/sell attempts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                pool_address TEXT NOT NULL,
                token_address TEXT NOT NULL,
                action TEXT NOT NULL,
                amount_in REAL,
                amount_out REAL,
                slippage_bps INTEGER,
                gas_price_gwei REAL,
                gas_used INTEGER,
                tx_hash TEXT UNIQUE,
                status TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                profit_eth REAL,
                notes TEXT,
                FOREIGN KEY (pool_address) REFERENCES pools(pool_address)
            )
        """)

        # Positions table - track open positions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                position_id TEXT PRIMARY KEY,
                token_address TEXT NOT NULL,
                entry_price REAL,
                quantity REAL,
                entry_tx TEXT,
                entry_timestamp TIMESTAMP,
                exit_price REAL,
                exit_tx TEXT,
                exit_timestamp TIMESTAMP,
                status TEXT,
                profit_loss_eth REAL,
                roi_percent REAL,
                take_profit_price REAL,
                stop_loss_price REAL
            )
        """)

        # PnL history table - daily/session snapshots
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pnl_history (
                snapshot_id TEXT PRIMARY KEY,
                snapshot_date DATE,
                wallet_balance_eth REAL,
                open_positions_count INTEGER,
                total_open_pnl_eth REAL,
                realized_pnl_eth REAL,
                daily_gas_spent_eth REAL,
                win_rate REAL,
                trade_count INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Safety scores table - detailed safety analysis
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS safety_scores (
                token_address TEXT PRIMARY KEY,
                overall_score INTEGER,
                liquidity_score INTEGER,
                holder_distribution_score INTEGER,
                mint_authority_score INTEGER,
                tax_score INTEGER,
                rug_probability_score INTEGER,
                honeypot_score INTEGER,
                analysis_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details TEXT
            )
        """)

        # Backtest results table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                backtest_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                start_date DATE,
                end_date DATE,
                initial_capital_eth REAL,
                final_capital_eth REAL,
                total_trades INTEGER,
                winning_trades INTEGER,
                losing_trades INTEGER,
                win_rate REAL,
                max_drawdown_percent REAL,
                total_fees_eth REAL,
                roi_percent REAL,
                sharpe_ratio REAL,
                parameters TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # A/B test tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ab_tests (
                test_id TEXT PRIMARY KEY,
                variant_a_params TEXT,
                variant_b_params TEXT,
                variant_a_trades INTEGER DEFAULT 0,
                variant_b_trades INTEGER DEFAULT 0,
                variant_a_pnl REAL DEFAULT 0,
                variant_b_pnl REAL DEFAULT 0,
                variant_a_win_rate REAL,
                variant_b_win_rate REAL,
                start_timestamp TIMESTAMP,
                end_timestamp TIMESTAMP,
                winner TEXT
            )
        """)

        # Events log - audit trail
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT,
                severity TEXT,
                message TEXT,
                data TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Token metadata cache
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS token_cache (
                token_address TEXT PRIMARY KEY,
                name TEXT,
                symbol TEXT,
                decimals INTEGER,
                total_supply REAL,
                meme_score REAL,
                is_b20 BOOLEAN,
                fetch_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    # =========== POOL OPERATIONS ===========
    def add_pool(
        self, pool_address: str, token_address: str, token_name: str,
        token_symbol: str, fee_tier: int, liquidity_eth: float = 0.0,
        safety_score: int = 0
    ) -> bool:
        """Add a new pool to tracking."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO pools
                (pool_address, token_address, token_name, token_symbol, fee_tier, liquidity_eth, safety_score)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (pool_address, token_address, token_name, token_symbol, fee_tier, liquidity_eth, safety_score))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding pool: {e}")
            return False

    def get_pool(self, pool_address: str) -> Optional[Dict]:
        """Get pool details."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pools WHERE pool_address = ?", (pool_address,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_pools(self, limit: int = 100) -> List[Dict]:
        """Get all tracked pools."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pools ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def update_pool_safety_score(self, pool_address: str, score: int, details: Dict) -> bool:
        """Update pool safety score."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE pools SET safety_score = ? WHERE pool_address = ?
            """, (score, pool_address))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating pool safety score: {e}")
            return False

    # =========== TRADE OPERATIONS ===========
    def log_trade(
        self, trade_id: str, pool_address: str, token_address: str, action: str,
        amount_in: float, amount_out: float, slippage_bps: int, gas_price_gwei: float,
        gas_used: int, tx_hash: str, status: str, profit_eth: float = 0.0, notes: str = ""
    ) -> bool:
        """Log a trade (buy/sell)."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades
                (trade_id, pool_address, token_address, action, amount_in, amount_out,
                 slippage_bps, gas_price_gwei, gas_used, tx_hash, status, profit_eth, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (trade_id, pool_address, token_address, action, amount_in, amount_out,
                  slippage_bps, gas_price_gwei, gas_used, tx_hash, status, profit_eth, notes))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error logging trade: {e}")
            return False

    def get_trades(self, limit: int = 50, status: Optional[str] = None) -> List[Dict]:
        """Get recent trades."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM trades WHERE status = ? ORDER BY timestamp DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_token_trades(self, token_address: str) -> List[Dict]:
        """Get all trades for a token."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM trades WHERE token_address = ? ORDER BY timestamp DESC",
            (token_address,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # =========== POSITION OPERATIONS ===========
    def open_position(
        self, position_id: str, token_address: str, entry_price: float,
        quantity: float, entry_tx: str, take_profit_price: float = 0.0,
        stop_loss_price: float = 0.0
    ) -> bool:
        """Open a new position."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO positions
                (position_id, token_address, entry_price, quantity, entry_tx, entry_timestamp,
                 status, take_profit_price, stop_loss_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (position_id, token_address, entry_price, quantity, entry_tx,
                  datetime.now(timezone.utc).isoformat(), "OPEN", take_profit_price, stop_loss_price))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error opening position: {e}")
            return False

    def close_position(
        self, position_id: str, exit_price: float, exit_tx: str, profit_eth: float, roi_percent: float
    ) -> bool:
        """Close an open position."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE positions
                SET exit_price = ?, exit_tx = ?, exit_timestamp = ?, status = ?, profit_loss_eth = ?, roi_percent = ?
                WHERE position_id = ?
            """, (exit_price, exit_tx, datetime.now(timezone.utc).isoformat(), "CLOSED", profit_eth, roi_percent, position_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error closing position: {e}")
            return False

    def get_open_positions(self) -> List[Dict]:
        """Get all open positions."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE status = 'OPEN'")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # =========== PNL OPERATIONS ===========
    def save_pnl_snapshot(
        self, snapshot_id: str, snapshot_date: str, wallet_balance_eth: float,
        open_positions_count: int, total_open_pnl_eth: float, realized_pnl_eth: float,
        daily_gas_spent_eth: float, win_rate: float, trade_count: int
    ) -> bool:
        """Save a PnL snapshot."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pnl_history
                (snapshot_id, snapshot_date, wallet_balance_eth, open_positions_count,
                 total_open_pnl_eth, realized_pnl_eth, daily_gas_spent_eth, win_rate, trade_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (snapshot_id, snapshot_date, wallet_balance_eth, open_positions_count,
                  total_open_pnl_eth, realized_pnl_eth, daily_gas_spent_eth, win_rate, trade_count))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving PnL snapshot: {e}")
            return False

    def get_pnl_history(self, days: int = 30) -> List[Dict]:
        """Get PnL history for N days."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM pnl_history
            WHERE snapshot_date >= date('now', ? || ' days')
            ORDER BY snapshot_date DESC
        """, (f"-{days}",))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # =========== SAFETY SCORE OPERATIONS ===========
    def save_safety_score(
        self, token_address: str, overall_score: int, liquidity_score: int,
        holder_score: int, mint_score: int, tax_score: int, rug_score: int,
        honeypot_score: int, details: Dict
    ) -> bool:
        """Save safety analysis results."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO safety_scores
                (token_address, overall_score, liquidity_score, holder_distribution_score,
                 mint_authority_score, tax_score, rug_probability_score, honeypot_score, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (token_address, overall_score, liquidity_score, holder_score, mint_score,
                  tax_score, rug_score, honeypot_score, json.dumps(details)))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving safety score: {e}")
            return False

    def get_safety_score(self, token_address: str) -> Optional[Dict]:
        """Get cached safety score."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM safety_scores WHERE token_address = ?", (token_address,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    # =========== EVENT LOGGING ===========
    def log_event(self, event_type: str, severity: str, message: str, data: Dict = None) -> bool:
        """Log an event for audit trail."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO events (event_type, severity, message, data)
                VALUES (?, ?, ?, ?)
            """, (event_type, severity, message, json.dumps(data or {})))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error logging event: {e}")
            return False

    def get_events(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict]:
        """Get recent events."""
        conn = self.get_connection()
        cursor = conn.cursor()
        if event_type:
            cursor.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                (event_type, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # =========== ANALYTICS ===========
    def get_win_rate(self, days: int = 30) -> float:
        """Calculate win rate for last N days."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN profit_eth > 0 THEN 1 END) as wins,
                COUNT(*) as total
            FROM trades
            WHERE status = 'success' AND datetime(timestamp) >= datetime('now', ? || ' days')
        """, (f"-{days}",))
        row = cursor.fetchone()
        conn.close()
        if row and row[1] > 0:
            return (row[0] / row[1]) * 100
        return 0.0

    def get_stats(self) -> Dict[str, Any]:
        """Get overall bot statistics."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Total trades
        cursor.execute("SELECT COUNT(*) FROM trades")
        total_trades = cursor.fetchone()[0]
        
        # Successful trades
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'success'")
        successful_trades = cursor.fetchone()[0]
        
        # Total PnL
        cursor.execute("SELECT SUM(profit_eth) FROM trades WHERE status = 'success'")
        total_pnl = cursor.fetchone()[0] or 0.0
        
        # Open positions
        cursor.execute("SELECT COUNT(*) FROM positions WHERE status = 'OPEN'")
        open_positions = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "total_trades": total_trades,
            "successful_trades": successful_trades,
            "total_pnl_eth": total_pnl,
            "open_positions": open_positions,
            "win_rate": (successful_trades / total_trades * 100) if total_trades > 0 else 0.0
        }

    def export_trades_csv(self, filepath: str) -> bool:
        """Export trades to CSV."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")
            rows = cursor.fetchall()
            conn.close()
            
            if not rows:
                return False
            
            import csv
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([desc[0] for desc in cursor.description])
                writer.writerows(rows)
            return True
        except Exception as e:
            print(f"Error exporting CSV: {e}")
            return False
