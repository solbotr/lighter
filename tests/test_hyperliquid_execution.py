#!/usr/bin/env python3
"""
Unit Tests for Hyperliquid Execution Client (test_hyperliquid_execution.py)
===========================================================================
"""

from __future__ import annotations

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hyperliquid_execution import (
    HyperliquidExecutionClient,
    HLOrderType,
    HLPosition,
)


def test_hyperliquid_client_initialization():
    client = HyperliquidExecutionClient(
        master_wallet="0x5cE95F8F7594c082549B34A32c26f4bf2F1bcFe9",
        agent_wallet="0xC0c5Ec3ba6d712F8202214161A3d4c575C5BBbdc",
        agent_private_key="0x128cb2a3840eb110c665e693bff80a0f0ad593611dadbe75cc0f637ef5365a3c",
    )
    assert client.master_wallet == "0x5cE95F8F7594c082549B34A32c26f4bf2F1bcFe9"
    assert client.agent_wallet == "0xC0c5Ec3ba6d712F8202214161A3d4c575C5BBbdc"


def test_hyperliquid_format_status_report():
    client = HyperliquidExecutionClient()
    positions = [
        HLPosition(
            coin="SOL",
            size=10.0,
            entry_price=195.50,
            unrealized_pnl=45.0,
            leverage=5.0,
            liquidation_price=150.0,
        )
    ]
    html = client.format_status_report_html(account_val=1500.0, positions=positions)
    assert "HYPERLIQUID PRO ACCOUNT DASHBOARD" in html
    assert "$1,500.00 USD" in html
    assert "SOL" in html
    assert "$+45.00" in html
