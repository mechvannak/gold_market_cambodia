"""Combine news, macro and technical scores into a forecast with buy/sell levels."""
import math
import time
from datetime import datetime, timezone

import pandas as pd

from .analysis import clip, macro_score, technicals
from .config import settings

WEIGHTS = {"news": 0.40, "macro": 0.30, "technical": 0.30}
DISCLAIMER = (
    "Educational model output, not financial advice. Gold can move sharply on unexpected news; "
    "size positions so a stop-out is affordable."
)


def _bias(c: float) -> str:
    return "bullish" if c >= 0.2 else "bearish" if c <= -0.2 else "neutral"


def compute_forecast(gold: pd.DataFrame, macro: dict[str, pd.DataFrame], news: dict, items: list[dict] | None = None) -> dict:
    tech = technicals(gold)
    mac = macro_score(macro)
    parts = {"news": news["score"], "macro": mac["score"], "technical": tech["score"]}
    composite = clip(sum(parts[k] * WEIGHTS[k] for k in WEIGHTS))
    bias = _bias(composite)

    agree = sum(1 for v in parts.values() if v * composite > 0) / 3 if composite else 0.0
    conf = min(1.0, abs(composite) * 1.6) * (0.6 + 0.4 * agree)
    confidence = "high" if conf >= 0.6 else "medium" if conf >= 0.35 else "low"

    price, a = tech["price"], tech["atr"]
    s = composite

    # Buy zone sits below the market, deeper when sentiment is weak; sell zone above, farther when strong.
    buy_c = price - a * (0.8 - 0.5 * s)
    buy_lo, buy_hi = buy_c - 0.25 * a, buy_c + 0.25 * a
    if buy_lo < tech["support"] - 0.5 * a:  # don't go absurdly far below recent support
        buy_lo = tech["support"] - 0.5 * a
        buy_hi = max(buy_hi, buy_lo + 0.3 * a)
    sell_c = price + a * (1.0 + 0.8 * s)
    sell_lo, sell_hi = sell_c - 0.25 * a, sell_c + 0.25 * a
    stop = buy_lo - 0.75 * a
    entry = (buy_lo + buy_hi) / 2
    rr = (sell_c - entry) / max(entry - stop, 1e-9)

    if bias == "bullish":
        action, note = "BUY ON DIPS", "Scores lean bullish: look to buy pullbacks into the buy zone, take profit into the sell zone."
    elif bias == "bearish":
        action, note = "SELL RALLIES / STAY LIGHT", "Scores lean bearish: avoid chasing, sell strength into the sell zone, buy only deep dips."
    else:
        action, note = "WAIT / RANGE TRADE", "Mixed signals: trade the range between buy and sell zones with small size, or wait."
    if rr < 1.2 and bias != "bearish":
        note += " Reward/risk is thin; consider waiting for a deeper dip."

    horizons = {}
    for label, days in (("1d", 1), ("1w", 5), ("1m", 21)):
        drift = composite * 0.5 * a * math.sqrt(days)
        spread = a * math.sqrt(days)
        horizons[label] = {
            "expected": round(price + drift, 2),
            "low": round(price + drift - spread, 2),
            "high": round(price + drift + spread, 2),
        }

    hist = gold.tail(90)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "price": round(price, 2),
        "composite": round(composite, 3),
        "bias": bias,
        "confidence": confidence,
        "action": action,
        "note": note,
        "scores": {k: round(v, 3) for k, v in parts.items()},
        "weights": WEIGHTS,
        "levels": {
            "buy_zone": [round(buy_lo, 2), round(buy_hi, 2)],
            "sell_zone": [round(sell_lo, 2), round(sell_hi, 2)],
            "stop": round(stop, 2),
            "support": round(tech["support"], 2),
            "resistance": round(tech["resistance"], 2),
            "reward_risk": round(rr, 2),
        },
        "horizons": horizons,
        "technical": {k: round(tech[k], 3) for k in ("rsi", "atr", "sma20", "sma50", "sma200", "mom20")},
        "macro": mac["components"],
        "news": {
            "summary": news["summary"],
            "drivers": news["drivers"],
            "method": news["method"],
            "n_items": news["n_items"],
            "headlines": [
                {"title": i["title"], "source": i["source"], "link": i["link"]} for i in (items or [])[:8]
            ],
        },
        "history": {
            "dates": [d.strftime("%Y-%m-%d") for d in hist.index],
            "close": [round(float(x), 2) for x in hist["Close"]],
        },
        "disclaimer": DISCLAIMER,
    }


_cache: dict = {"t": 0.0, "value": None}


def get_forecast(force: bool = False) -> dict:
    """Fetch live data, score it, and cache the result for CACHE_TTL_SECONDS."""
    if not force and _cache["value"] and time.time() - _cache["t"] < settings.cache_ttl:
        return _cache["value"]
    from .data import fetch_market
    from .llm import score_news
    from .news import fetch_news

    gold, macro = fetch_market()
    items = fetch_news()
    news = score_news(items)
    value = compute_forecast(gold, macro, news, items)
    _cache.update(t=time.time(), value=value)
    return value
