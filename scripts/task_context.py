"""Facts for the Claude scheduled task, so it never has to do date maths or guess its mode.

  python scripts/task_context.py        prints one JSON object

Reads only public files (data/market.json, data/analysis.json). No network, no secrets.
"""
import json
import sys
from datetime import datetime, timedelta

from compose import load_json
from decide import market_decision
from market import MARKET_JSON, ROOT, now_pp

ANALYSIS_JSON = ROOT / "data" / "analysis.json"
BIG_MOVE_PCT = 3.0


def first_weekday_of_month(now: datetime):
    day = now.replace(day=1).date()
    while day.weekday() >= 5:  # Saturday / Sunday
        day += timedelta(days=1)
    return day


def run_slot(now: datetime) -> str:
    return "morning" if now.hour < 14 else "evening"


def pick_mode(now: datetime) -> str:
    """monthly: first weekday of the month (morning run) · weekly: Monday morning · else watchdog."""
    if run_slot(now) == "morning":
        if now.date() == first_weekday_of_month(now):
            return "monthly"
        if now.weekday() == 0:
            return "weekly"
    return "watchdog"


def context(now: datetime, market: dict | None, prev: dict | None) -> dict:
    out = {
        "now": now.isoformat(timespec="minutes"),
        "weekday": now.strftime("%A"),
        "slot": run_slot(now),
        "mode": pick_mode(now),
        "first_weekday_of_month": first_weekday_of_month(now).isoformat(),
        "market_ok": False,
    }
    if not market:
        out["problem"] = "data/market.json is missing: do not write an analysis; stop and say so"
        return out
    age_days = (now.date() - datetime.fromisoformat(market["date"]).date()).days
    out["market_date"] = market["date"]
    out["market_age_days"] = age_days
    out["market_ok"] = age_days <= 3  # Friday data is still current on Monday morning
    if not out["market_ok"]:
        out["problem"] = "data/market.json is older than 3 days: do not write an analysis; stop and say so"
    out["price_oz"] = market["price_oz"]
    out["market_decision"] = market_decision(market)

    prev = prev or {}
    out["previous_generated_at"] = prev.get("generated_at")
    out["previous_market_decision"] = prev.get("market_decision")
    out["decision_changed"] = bool(prev.get("market_decision")) and prev["market_decision"] != out["market_decision"]
    try:
        move = (float(market["price_oz"]) / float(prev["price_at"]) - 1) * 100
        out["price_move_pct_since_previous"] = round(move, 2)
        out["big_price_move"] = abs(move) >= BIG_MOVE_PCT
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        out["price_move_pct_since_previous"] = None
        out["big_price_move"] = False
    out["watchdog_should_notify_without_news"] = out["decision_changed"] or out["big_price_move"]
    return out


def main() -> int:
    print(json.dumps(context(now_pp(), load_json(MARKET_JSON), load_json(ANALYSIS_JSON)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
