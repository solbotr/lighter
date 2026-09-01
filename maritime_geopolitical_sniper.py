#!/usr/bin/env python3
"""
Maritime, Chokepoint & Geopolitical Incident Sniper for zkLighter (maritime_geopolitical_sniper.py)
================================================================================================
Monitors real-time geopolitical intelligence, naval chokepoints (Red Sea, Hormuz,
Suez Canal, Panama Canal), energy pipeline incidents, and defense/space developments.

Automatically maps critical geopolitical escalations to high-conviction trade signals:
- Oil & Gas infrastructure incidents -> Long BRENTOIL, WTI, NATGAS
- Safe haven war escalations -> Long XAU (Gold), XAG (Silver)
- Defense & Space contracts -> Long PLTR, RKLB
- Maritime shipping bottlenecks -> Long BRENTOIL, WTI, WHEAT
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import aiohttp

logger = logging.getLogger("MaritimeGeopoliticalSniper")

# Critical Geopolitical Chokepoints & Asset Mappings
CHOKEPOINT_RULES: Dict[str, Dict[str, Any]] = {
    "RED_SEA_HORMUZ": {
        "keywords": [
            "red sea", "strait of hormuz", "bab el-mandeb", "houthi", "tanker attacked",
            "vessel struck", "missile fired", "oil tanker seized", "gulf of aden", "drone strike"
        ],
        "assets": ["BRENTOIL", "WTI", "NATGAS", "XAU"],
        "direction": "BULLISH",
        "confidence": 0.92,
        "catalyst_type": "GEOPOLITICAL_OIL_CHOKEPOINT",
    },
    "ENERGY_INFRASTRUCTURE": {
        "keywords": [
            "pipeline blast", "refinery fire", "oil terminal attack", "gas shutdown",
            "pipeline leak", "nord stream", "energy infrastructure struck", "oil depot"
        ],
        "assets": ["BRENTOIL", "WTI", "NATGAS"],
        "direction": "BULLISH",
        "confidence": 0.94,
        "catalyst_type": "ENERGY_SUPPLY_DISRUPTION",
    },
    "SAFE_HAVEN_WAR_ESCALATION": {
        "keywords": [
            "military invasion", "airspace closed", "icbm launch", "nuclear threat",
            "war declared", "emergency un session", "air strikes launched", "carrier strike group"
        ],
        "assets": ["XAU", "XAG", "PLTR", "RKLB"],
        "direction": "BULLISH",
        "confidence": 0.90,
        "catalyst_type": "WAR_ESCALATION_SAFE_HAVEN",
    },
    "CANAL_BOTTLENECK": {
        "keywords": [
            "suez canal blocked", "panama canal drought", "container ship grounded",
            "canal traffic suspended", "maritime shipping grounded"
        ],
        "assets": ["BRENTOIL", "WTI", "WHEAT"],
        "direction": "BULLISH",
        "confidence": 0.88,
        "catalyst_type": "MARITIME_CHOKEPOINT_BOTTLENECK",
    },
    "DEFENSE_SPACE_EXPANSION": {
        "keywords": [
            "pentagon contract", "defense satellite launch", "space force contract",
            "dod missile defense", "classified satellite", "surveillance contract"
        ],
        "assets": ["PLTR", "RKLB"],
        "direction": "BULLISH",
        "confidence": 0.89,
        "catalyst_type": "DEFENSE_SPACE_CONTRACT",
    },
}

# Public Global Intelligence & Maritime Incident Sources
OSINT_INCIDENT_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/MiddleEast.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://defence-blog.com/feed/",
    "https://maritime-executive.com/rss",
    "https://gcaptain.com/feed/",
]


@dataclass
class GeopoliticalIncident:
    """Standardized geopolitical or maritime threat alert."""
    incident_id: str
    headline: str
    chokepoint_type: str
    target_assets: List[str]
    direction: str
    confidence: float
    source: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "headline": self.headline,
            "chokepoint_type": self.chokepoint_type,
            "target_assets": self.target_assets,
            "direction": self.direction,
            "confidence": self.confidence,
            "source": self.source,
            "timestamp": self.timestamp,
        }


class MaritimeGeopoliticalSniper:
    """
    Sub-second Geopolitical Chokepoint & Maritime Intelligence Ingestion Engine.
    """

    def __init__(
        self,
        on_incident_callback: Optional[Callable[[GeopoliticalIncident], Any]] = None,
        poll_interval_seconds: float = 12.0,
    ):
        self.on_incident_callback = on_incident_callback
        self.poll_interval_seconds = poll_interval_seconds
        self._seen_hashes: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        self._running = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) zkLighterOSINT/2.0"}
            )
        return self._session

    def evaluate_text(self, text: str, source: str = "OSINT") -> Optional[GeopoliticalIncident]:
        """Evaluates raw headline/text against geopolitical chokepoint intelligence rules."""
        clean_text = (text or "").lower()
        if len(clean_text) < 10:
            return None

        for rule_id, config in CHOKEPOINT_RULES.items():
            matched_keywords = [kw for kw in config["keywords"] if kw in clean_text]
            if matched_keywords:
                incident_hash = hashlib.md5(f"{rule_id}_{clean_text[:60]}".encode()).hexdigest()
                if incident_hash in self._seen_hashes:
                    return None
                self._seen_hashes.add(incident_hash)
                if len(self._seen_hashes) > 1000:
                    self._seen_hashes.clear()

                incident = GeopoliticalIncident(
                    incident_id=incident_hash[:12],
                    headline=text.strip(),
                    chokepoint_type=config["catalyst_type"],
                    target_assets=config["assets"],
                    direction=config["direction"],
                    confidence=config["confidence"],
                    source=source,
                    timestamp=time.time(),
                )
                return incident
        return None

    async def poll_sources(self) -> List[GeopoliticalIncident]:
        """Polls raw OSINT RSS and maritime incident channels."""
        session = await self._get_session()
        incidents = []

        for feed_url in OSINT_INCIDENT_FEEDS:
            try:
                async with session.get(feed_url, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", content, re.IGNORECASE)
                        for t in titles[1:15]:
                            inc = self.evaluate_text(t, source=feed_url)
                            if inc:
                                incidents.append(inc)
                                logger.info("🌍 [GEOPOLITICAL SNIPER] Detected: %s -> Assets: %s", inc.headline, inc.target_assets)
            except Exception as e:
                logger.debug("Incident feed error %s: %s", feed_url, e)

        return incidents

    async def start(self) -> None:
        """Runs the 24/7 background geopolitical and maritime chokepoint monitor."""
        self._running = True
        logger.info("🌍 [Maritime Geopolitical Sniper] Active. Monitoring Red Sea, Hormuz, Energy & Defense catalysts...")
        while self._running:
            try:
                incidents = await self.poll_sources()
                for inc in incidents:
                    if self.on_incident_callback:
                        res = self.on_incident_callback(inc)
                        if asyncio.iscoroutine(res):
                            await res
            except Exception as e:
                logger.error("Geopolitical sniper polling loop exception: %s", e)
            await asyncio.sleep(self.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())
