#!/usr/bin/env python3
"""
Email Notification Client via Resend (email_notifier.py)
========================================================
Non-blocking trade and safety alerts for the Lighter bot over
https://api.resend.com/emails. Same fire-and-forget design as
poke_notifier.py: bounded queue + daemon thread, stdlib only.

Env:
  RESEND_API_KEY  (required, starts with re_)
  EMAIL_FROM      (e.g. alerts@yourdomain.com; must be verified in Resend)
  EMAIL_TO        (destination inbox)

Fail-closed when the key is unset. Secrets are scrubbed before send.
"""

from __future__ import annotations

import html as _html
import json
import logging
import os
import queue
import re
import threading
import urllib.request
from typing import Optional

from dotenv import load_dotenv

load_dotenv(override=False)

logger = logging.getLogger("EmailNotifier")

RESEND_API_URL = "https://api.resend.com/emails"

_EMAIL_QUEUE: queue.Queue = queue.Queue(maxsize=200)
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _scrub(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"[0-9a-fA-F]{64}", "[REDACTED_KEY]", text)
    text = re.sub(r"eyJ[a-zA-Z0-9_\-\.]{20,}", "[REDACTED_TOKEN]", text)
    text = re.sub(r"re_[a-zA-Z0-9_\-]{10,}", "[REDACTED_RESEND_KEY]", text)
    return text


def _config() -> tuple[str, str, str]:
    return (
        (os.getenv("RESEND_API_KEY", "") or "").strip(),
        (os.getenv("EMAIL_FROM", "") or "").strip(),
        (os.getenv("EMAIL_TO", "") or "").strip(),
    )


class EmailWorker(threading.Thread):
    """Background daemon worker POSTing to Resend without blocking trading."""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="EmailNotifierWorker")
        self.is_running = True

    def run(self) -> None:
        while self.is_running:
            try:
                subject, body_html = _EMAIL_QUEUE.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._dispatch(subject, body_html)
            except Exception as e:
                logger.debug("Resend dispatch exception: %s", e)
            finally:
                _EMAIL_QUEUE.task_done()

    def _dispatch(self, subject: str, body_html: str) -> None:
        api_key, sender, recipient = _config()
        if not api_key:
            return
        payload = json.dumps({
            "from": sender,
            "to": [recipient],
            "subject": _scrub(subject)[:200],
            "html": _scrub(body_html)[:20000],
        }).encode("utf-8")
        req = urllib.request.Request(
            RESEND_API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # api.resend.com sits behind Cloudflare: a browser UA avoids 403s.
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            if resp.status == 200:
                logger.debug("Resend email delivered: %s", subject[:60])
            else:
                logger.warning("Resend returned HTTP %s", resp.status)


def _ensure_worker_started() -> None:
    global _WORKER_STARTED
    if not _WORKER_STARTED:
        with _WORKER_LOCK:
            if not _WORKER_STARTED:
                EmailWorker().start()
                _WORKER_STARTED = True
                logger.info("Email notification worker started (Resend)")


def email_configured() -> bool:
    if os.getenv("EMAIL_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    api_key, sender, recipient = _config()
    return bool(api_key and sender and recipient)


def email_send(subject: str, body_html: str) -> bool:
    """Non-blocking email dispatch. Fail-closed when unconfigured."""
    if not subject:
        return False
    if not email_configured():
        logger.debug("Resend/EMAIL_* not configured; skipping email")
        return False
    _ensure_worker_started()
    try:
        _EMAIL_QUEUE.put_nowait((subject, body_html))
        return True
    except queue.Full:
        logger.warning("Email queue full; dropping message")
        return False


def _card(title: str, rows: list[tuple[str, str]]) -> str:
    items = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#888'>{_html.escape(k)}</td>"
        f"<td style='padding:4px 0'><b>{_html.escape(v)}</b></td></tr>"
        for k, v in rows
    )
    return (
        f"<div style='font-family:monospace;background:#0a0a0a;color:#eee;"
        f"padding:16px;border-radius:8px;max-width:560px'>"
        f"<h3 style='margin:0 0 8px'>{_html.escape(title)}</h3>"
        f"<table>{items}</table></div>"
    )


def email_send_trade_alert(asset: str, side: str, price: float, notional_usd: float,
                           tp_price: Optional[float] = None, sl_price: Optional[float] = None,
                           reason: str = "CATALYST_SNIPE") -> bool:
    return email_send(
        f"Lighter FILL: {side} {asset} ${notional_usd:,.0f}",
        _card(f"TRADE EXECUTED: {side} {asset}", [
            ("Entry", f"${price:,.4f}"),
            ("Notional", f"${notional_usd:,.2f}"),
            ("Take profit", f"${tp_price:,.4f}" if tp_price else "-"),
            ("Stop loss", f"${sl_price:,.4f}" if sl_price else "-"),
            ("Trigger", reason[:120]),
        ]),
    )


def email_send_exit_alert(asset: str, exit_type: str, pnl_usd: float,
                          pnl_pct: float, exit_price: float) -> bool:
    return email_send(
        f"Lighter EXIT: {asset} {pnl_pct:+.2f}% (${pnl_usd:+.2f})",
        _card(f"POSITION CLOSED ({exit_type})", [
            ("Asset", asset),
            ("Exit", f"${exit_price:,.4f}"),
            ("Realized PnL", f"{pnl_pct:+.2f}% (${pnl_usd:+.2f})"),
        ]),
    )


def email_send_kill_alert(reason: str) -> bool:
    return email_send(
        "Lighter KILL SWITCH ENGAGED",
        _card("KILL SWITCH ENGAGED", [("Reason", reason[:200])]),
    )


def email_send_boot_notice(mode: str, markets: int, sources: int) -> bool:
    return email_send(
        f"Lighter bot started ({mode})",
        _card("BOT BOOT", [
            ("Mode", mode),
            ("Markets", str(markets)),
            ("News sources", str(sources)),
        ]),
    )
