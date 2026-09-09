#!/usr/bin/env python3
"""
Enhanced Telegram Bot with Button Commands
==========================================
Full interactive bot with inline button menus
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler,
        ContextTypes, MessageHandler, filters
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False


class TelegramBotEnhanced:
    """Enhanced Telegram bot with button-based interface."""

    def __init__(self, bot_token: str, user_id: int):
        self.bot_token = bot_token
        self.user_id = user_id
        self.app = None

    def initialize(self, db_manager, risk_manager, w3):
        """Initialize with bot dependencies."""
        self.db_manager = db_manager
        self.risk_manager = risk_manager
        self.w3 = w3
        
        if TELEGRAM_AVAILABLE:
            self.app = Application.builder().token(self.bot_token).build()
            self._setup_handlers()

    def _setup_handlers(self):
        """Register handlers."""
        if not self.app:
            return
        
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CallbackQueryHandler(self.button_click))

    # =========== START COMMAND ===========
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Main menu with button interface."""
        if update.effective_user.id != self.user_id:
            await update.message.reply_text("🚫 Unauthorized")
            return
        
        keyboard = [
            # Row 1: Status & Portfolio
            [
                InlineKeyboardButton("📊 Status", callback_data="btn_status"),
                InlineKeyboardButton("💰 Portfolio", callback_data="btn_portfolio"),
            ],
            # Row 2: Positions & Trades
            [
                InlineKeyboardButton("📈 Positions", callback_data="btn_positions"),
                InlineKeyboardButton("📝 Trades", callback_data="btn_trades"),
            ],
            # Row 3: Control
            [
                InlineKeyboardButton("⏸ Pause", callback_data="btn_pause"),
                InlineKeyboardButton("▶️ Resume", callback_data="btn_resume"),
            ],
            # Row 4: Settings
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="btn_settings"),
                InlineKeyboardButton("📊 Stats", callback_data="btn_stats"),
            ],
            # Row 5: Help
            [
                InlineKeyboardButton("❓ Help", callback_data="btn_help"),
                InlineKeyboardButton("🔄 Refresh", callback_data="btn_start"),
            ],
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = """
🤖 **B20 SNIPER BOT CONTROL PANEL**

Select an option below to:
• Monitor positions & PnL
• Control trading
• View statistics
• Manage settings

⚡ **Status:** 🟢 ACTIVE
"""
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            await update.callback_query.answer()
        else:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

    # =========== BUTTON HANDLERS ===========
    async def button_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button clicks."""
        if update.effective_user.id != self.user_id:
            await update.callback_query.answer("🚫 Unauthorized", show_alert=True)
            return
        
        query = update.callback_query
        action = query.data
        
        if action == "btn_start":
            await self.cmd_start(update, context)
        elif action == "btn_status":
            await self.show_status(update, context)
        elif action == "btn_portfolio":
            await self.show_portfolio(update, context)
        elif action == "btn_positions":
            await self.show_positions(update, context)
        elif action == "btn_trades":
            await self.show_trades(update, context)
        elif action == "btn_pause":
            await self.action_pause(update, context)
        elif action == "btn_resume":
            await self.action_resume(update, context)
        elif action == "btn_stats":
            await self.show_stats(update, context)
        elif action == "btn_settings":
            await self.show_settings(update, context)
        elif action == "btn_help":
            await self.show_help(update, context)

    # =========== STATUS ===========
    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot status with back button."""
        if not self.risk_manager:
            await update.callback_query.answer("Bot not initialized", show_alert=True)
            return
        
        stats = self.risk_manager.get_stats()
        db_stats = self.db_manager.get_stats() if self.db_manager else {}
        
        text = f"""
📊 **BOT STATUS**

**Active Positions:** {stats['open_positions']}/{stats['max_positions']}
**Daily Loss:** {stats['daily_loss_eth']:.4f} / {stats['daily_loss_limit_eth']:.4f} ETH
**Status:** {'🔴 PAUSED' if stats['is_paused'] else '🟢 RUNNING'}

**Quick Stats:**
• Win Rate: {db_stats.get('win_rate', 0):.1f}%
• Total PnL: {db_stats.get('total_pnl_eth', 0):+.4f} ETH
• Trades: {db_stats.get('total_trades', 0)}

🕐 Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="btn_status")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== PORTFOLIO ===========
    async def show_portfolio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show portfolio with charts."""
        if not self.risk_manager:
            await update.callback_query.answer("Bot not initialized", show_alert=True)
            return
        
        positions = self.risk_manager.get_positions()
        pnl_eth, pnl_percent = self.risk_manager.calculate_portfolio_pnl({})
        
        text = f"""
💰 **PORTFOLIO SNAPSHOT**

**Summary:**
• Open Positions: {len(positions)}
• Unrealized PnL: {pnl_eth:+.4f} ETH ({pnl_percent:+.1f}%)
• Status: {'🔴 Paused' if self.risk_manager.is_paused else '🟢 Active'}

**Recent Trades:**
"""
        
        if self.db_manager:
            trades = self.db_manager.get_trades(limit=5)
            for i, trade in enumerate(trades, 1):
                status_emoji = "✅" if trade['status'] == 'success' else "❌"
                text += f"\n{status_emoji} {trade['action'].upper()}: {trade['profit_eth']:+.4f} ETH"
        else:
            text += "\n(Database unavailable)"
        
        keyboard = [
            [InlineKeyboardButton("📈 Positions", callback_data="btn_positions")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="btn_portfolio")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== POSITIONS ===========
    async def show_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show open positions."""
        if not self.risk_manager:
            await update.callback_query.answer("Bot not initialized", show_alert=True)
            return
        
        positions = self.risk_manager.get_positions()
        
        if not positions:
            text = "📭 **No open positions**\n\nWaiting for the next B20 launch..."
        else:
            text = f"📈 **OPEN POSITIONS** ({len(positions)})\n\n"
            for i, pos in enumerate(positions, 1):
                text += f"""
**Position {i}:**
• Token: `{pos.token_address[:8]}...`
• Entry: {pos.entry_price:.8f} ETH
• Qty: {pos.quantity:.4f}
• Age: {(datetime.now(timezone.utc) - pos.entry_time).total_seconds()/60:.0f}m
• SL: {pos.stop_loss_price:.8f}
"""
        
        keyboard = [
            [InlineKeyboardButton("💰 Portfolio", callback_data="btn_portfolio")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="btn_positions")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== TRADES ===========
    async def show_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show recent trades."""
        if not self.db_manager:
            text = "📊 Database unavailable"
        else:
            trades = self.db_manager.get_trades(limit=10)
            text = f"📝 **RECENT TRADES** ({len(trades)})\n\n"
            
            for trade in trades:
                status_icon = "✅" if trade['status'] == 'success' else "❌"
                profit_display = f"{trade['profit_eth']:+.4f}" if trade['profit_eth'] else "N/A"
                text += f"{status_icon} {trade['action'].upper()}: {profit_display} ETH\n"
        
        keyboard = [
            [InlineKeyboardButton("💰 Portfolio", callback_data="btn_portfolio")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="btn_trades")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== STATS ===========
    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed statistics."""
        if not self.db_manager:
            text = "📊 Database unavailable"
        else:
            stats = self.db_manager.get_stats()
            text = f"""
📊 **DETAILED STATISTICS**

**Trading Performance:**
• Total Trades: {stats.get('total_trades', 0)}
• Successful: {stats.get('successful_trades', 0)}
• Win Rate: {stats.get('win_rate', 0):.1f}%
• Total PnL: {stats.get('total_pnl_eth', 0):+.4f} ETH

**Current Position:**
• Open Positions: {stats.get('open_positions', 0)}
• Status: {'🟢 RUNNING' if not self.risk_manager.is_paused else '🔴 PAUSED'}
"""
        
        keyboard = [
            [InlineKeyboardButton("💰 Portfolio", callback_data="btn_portfolio")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="btn_stats")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== PAUSE/RESUME ===========
    async def action_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause trading."""
        if self.risk_manager:
            self.risk_manager.pause()
            await update.callback_query.answer("⏸ Bot paused", show_alert=True)
            if self.db_manager:
                self.db_manager.log_event("bot_paused", "warning", "User paused bot via Telegram")
            await self.cmd_start(update, context)

    async def action_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume trading."""
        if self.risk_manager:
            self.risk_manager.resume()
            await update.callback_query.answer("▶️ Bot resumed", show_alert=True)
            if self.db_manager:
                self.db_manager.log_event("bot_resumed", "info", "User resumed bot via Telegram")
            await self.cmd_start(update, context)

    # =========== SETTINGS ===========
    async def show_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show settings menu."""
        if not self.risk_manager:
            text = "⚙️ Settings unavailable"
        else:
            stats = self.risk_manager.get_stats()
            text = f"""
⚙️ **BOT SETTINGS**

**Risk Management:**
• Max Position Size: {self.risk_manager.max_position_eth:.4f} ETH
• Max Positions: {stats['max_positions']}
• Daily Loss Limit: {stats['daily_loss_limit_eth']:.4f} ETH
• Current Daily Loss: {stats['daily_loss_eth']:.4f} ETH

**Blacklisted Tokens:** {stats['blacklisted_count']}

**Bot Status:** {'🔴 PAUSED' if stats['is_paused'] else '🟢 RUNNING'}

_Use Telegram to pause/resume trading._
"""
        
        keyboard = [
            [InlineKeyboardButton("⏸ Pause", callback_data="btn_pause"),
             InlineKeyboardButton("▶️ Resume", callback_data="btn_resume")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== HELP ===========
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help menu."""
        text = """
❓ **HELP GUIDE**

**Main Features:**

📊 **Status** - View bot status & quick stats
💰 **Portfolio** - Portfolio snapshot & recent trades
📈 **Positions** - List all open positions
📝 **Trades** - View recent trade history
📊 **Stats** - Detailed trading statistics
⚙️ **Settings** - Bot configuration

**Controls:**
⏸ **Pause** - Stop trading (keep bot running)
▶️ **Resume** - Resume trading

**How to Use:**

1. Click buttons to navigate
2. Use **🔄 Refresh** to update data
3. Use **◀️ Back** to return to main menu

**Bot Features:**
• Real-time pool detection
• Automatic buy/sell
• Honeypot protection
• Position management
• Trade history tracking

_For manual commands, update in .env file._
"""
        
        keyboard = [
            [InlineKeyboardButton("📊 Status", callback_data="btn_status")],
            [InlineKeyboardButton("◀️ Back", callback_data="btn_start")],
        ]
        
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        await update.callback_query.answer()

    # =========== ALERTS ===========
    async def send_pool_alert(self, token_name: str, token_symbol: str, liquidity_eth: float, safety_score: int):
        """Send new pool alert."""
        if not TELEGRAM_AVAILABLE or not self.app:
            return
        
        keyboard = [
            [InlineKeyboardButton("✅ Buy", callback_data=f"buy_{token_symbol}"),
             InlineKeyboardButton("❌ Skip", callback_data="skip")],
            [InlineKeyboardButton("📊 Check", callback_data="btn_status")],
        ]
        
        text = f"""
🚨 **NEW POOL DETECTED!**

**Token:** {token_name} ({token_symbol})
**Liquidity:** {liquidity_eth:.2f} ETH
**Safety Score:** {safety_score}/100

_Auto-buy enabled. Click to override._
"""
        
        try:
            await self.app.bot.send_message(
                chat_id=self.user_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            print(f"Failed to send alert: {e}")

    async def start_polling(self):
        """Start bot."""
        if not self.app:
            return
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def stop(self):
        """Stop bot."""
        if self.app:
            await self.app.stop()
