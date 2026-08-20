from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Sequence

from .config import Settings
from .news.models import NewsEvent
from .runtime import DemoMarketProvider, NewsProvider, PaperTradingLoop, RunSummary


class RssNewsProvider:
    def __init__(self, urls: Sequence[str]) -> None:
        self.urls = tuple(urls)

    async def fetch(self) -> Sequence[NewsEvent]:
        import feedparser

        events: list[NewsEvent] = []
        for url in self.urls:
            parsed = await asyncio.to_thread(feedparser.parse, url)
            for entry in parsed.entries:
                title = str(entry.get("title", "")).strip()
                if not title:
                    continue
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published is None:
                    continue
                published_at = datetime(*published[:6], tzinfo=timezone.utc)
                events.append(
                    NewsEvent(
                        source=url,
                        title=title,
                        body=str(entry.get("summary", "")),
                        published_at=published_at,
                        url=str(entry.get("link", "")),
                        source_score=0.8,
                        entities=("BTC",),
                    )
                )
        return events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lighter-paper", description="Run the fail-closed Lighter paper trading loop")
    parser.add_argument("--mode", choices=("paper", "live"), default=None)
    parser.add_argument("--iterations", type=int, default=1, help="number of cycles; 0 runs continuously")
    parser.add_argument("--interval", type=float, default=None, help="seconds between cycles")
    parser.add_argument("--news-url", action="append", default=[], help="RSS/Atom URL; repeatable")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def _summary(summary: RunSummary) -> str:
    return (
        f"iterations={summary.iterations} events={summary.events} signals={summary.signals} "
        f"approved={summary.approved} rejected={summary.rejected} paper_orders={summary.orders}"
    )


async def run_command(args: argparse.Namespace) -> RunSummary:
    settings = Settings.from_env()
    if args.mode is not None:
        settings = type(settings)(**{**settings.__dict__, "mode": args.mode})
        settings.validate()
    if settings.mode != "paper":
        raise ValueError("lighter-paper refuses live mode; set LIGHTER_MODE=paper")
    if args.iterations < 0:
        raise ValueError("--iterations must not be negative")
    provider: NewsProvider
    if args.news_url:
        provider = RssNewsProvider(args.news_url)
    else:
        from .runtime import DemoNewsProvider

        provider = DemoNewsProvider()
    loop = PaperTradingLoop(settings, provider, DemoMarketProvider())
    return await loop.run(args.iterations, args.interval)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    try:
        summary = asyncio.run(run_command(args))
    except (ValueError, KeyboardInterrupt) as exc:
        if not isinstance(exc, KeyboardInterrupt):
            parser.error(str(exc))
        return 130
    print(_summary(summary))
    return 0
