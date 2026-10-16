"""World economic / gold news headlines from public RSS feeds."""
import calendar
import time
from urllib.parse import quote_plus

import feedparser

QUERIES = [
    "gold price OR bullion",
    "Federal Reserve interest rates inflation",
    "US dollar Treasury yields",
    "central bank gold buying China India",
    "geopolitical tensions war sanctions",
    "oil prices OPEC economy recession",
]


def _google_news(q: str) -> str:
    return f"https://news.google.com/rss/search?q={quote_plus(q + ' when:2d')}&hl=en-US&gl=US&ceid=US:en"


FEEDS = [_google_news(q) for q in QUERIES] + ["https://www.fxstreet.com/rss/news"]


def fetch_news(max_items: int = 40, max_age_hours: int = 48) -> list[dict]:
    cutoff = time.time() - max_age_hours * 3600
    seen: set[str] = set()
    items: list[dict] = []
    for url in FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception:
            continue
        for e in feed.entries[:15]:
            title = (e.get("title") or "").strip()
            key = title.lower()[:80]
            if not title or key in seen:
                continue
            ts = calendar.timegm(e.published_parsed) if e.get("published_parsed") else time.time()
            if ts < cutoff:
                continue
            seen.add(key)
            src = ""
            if isinstance(e.get("source"), dict):
                src = e["source"].get("title", "")
            items.append(
                {
                    "title": title,
                    "source": src or feed.feed.get("title", ""),
                    "ts": ts,
                    "link": e.get("link", ""),
                }
            )
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:max_items]
