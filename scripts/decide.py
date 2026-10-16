"""Decision rules. First matching rule wins. Pure functions, no network, no secrets.

1. Profit >= 50% and gold >= 20% above its 200-day average -> sell in steps (keep a 30% core)
2. Gold >= 25% above its 200-day average                    -> reduce
3. Gold >= 15% above                                        -> wait (half the monthly buy)
4. Gold >= 8% below its 3-month high, or below 200-day avg  -> buy extra / buy in steps
5. Otherwise                                                -> hold / normal buy

Claude's news analysis may set confidence and soften a plan (see compose.py) but never changes
the action chosen here.
"""
import json
import sys
from pathlib import Path

OZ_GRAMS = 31.1034768
CHI_GRAMS = 3.75  # 1 chi of gold in Cambodia
CHI_PER_OZ = OZ_GRAMS / CHI_GRAMS

CORE_SHARE = 0.30
PROFIT_SELL = 0.50
ABOVE_SELL = 0.20
ABOVE_REDUCE = 0.25
ABOVE_WAIT = 0.15
DIP_FROM_HIGH = 0.08
REDUCE_SHARE = 0.15  # of holdings, never into the core
SELL_STEPS = 3

ACTIONS = ("SELL_STEPS", "REDUCE", "WAIT", "BUY_EXTRA", "BUY_STEPS", "HOLD")


def oz_to_chi(price_oz: float) -> float:
    return price_oz / CHI_PER_OZ


def holdings(purchases: list[dict]) -> dict:
    """Average-cost position from /buy and /sell records."""
    qty = cost = realized = 0.0
    for p in sorted(purchases, key=lambda x: (x.get("date", ""), x.get("id", 0))):
        chi, price = float(p["chi"]), float(p["price"])
        if p["type"] == "buy":
            qty += chi
            cost += chi * price
        else:
            avg = cost / qty if qty > 0 else price
            sold = min(chi, qty)
            realized += sold * (price - avg)
            qty -= sold
            cost -= sold * avg
    qty = round(qty, 6)
    return {
        "chi": max(qty, 0.0),
        "avg_cost": cost / qty if qty > 0 else 0.0,
        "invested": cost if qty > 0 else 0.0,
        "realized": realized,
    }


def decide(market: dict, hold: dict | None = None, ref_chi: float | None = None, monthly_chi: float = 1.0) -> dict:
    """Return the decision for today's market and (optionally) the owner's position.

    ref_chi is the $/chi price used to measure profit (shop buyback if known, else world price).
    """
    try:
        price, ma200, high3m = float(market["price_oz"]), float(market["ma200"]), float(market["high3m"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("market data is missing price_oz, ma200 or high3m") from exc
    if min(price, ma200, high3m) <= 0:
        raise ValueError("market data has non-positive values")

    hold = hold or {"chi": 0.0, "avg_cost": 0.0}
    above = price / ma200 - 1
    from_high = 1 - price / high3m  # how far below the 3-month high (positive = below)
    profit = None
    if hold["chi"] > 0 and hold["avg_cost"] > 0 and ref_chi:
        profit = ref_chi / hold["avg_cost"] - 1

    core = hold["chi"] * CORE_SHARE
    sellable = max(hold["chi"] - core, 0.0)
    out = {
        "rule": 5,
        "action": "HOLD",
        "buy_chi": float(monthly_chi),
        "sell_chi": 0.0,
        "steps": 1,
        "core_chi": round(core, 2),
        "above_200": above,
        "from_high": from_high,
        "profit": profit,
    }

    if profit is not None and profit >= PROFIT_SELL and above >= ABOVE_SELL:
        out.update(rule=1, action="SELL_STEPS", buy_chi=0.0, steps=SELL_STEPS, sell_chi=sellable / SELL_STEPS)
    elif above >= ABOVE_REDUCE:
        out.update(rule=2, action="REDUCE", buy_chi=0.0, sell_chi=min(hold["chi"] * REDUCE_SHARE, sellable))
    elif above >= ABOVE_WAIT:
        out.update(rule=3, action="WAIT", buy_chi=monthly_chi * 0.5)
    elif price < ma200:
        out.update(rule=4, action="BUY_STEPS", buy_chi=monthly_chi * 2.0, steps=3)
    elif from_high >= DIP_FROM_HIGH:
        out.update(rule=4, action="BUY_EXTRA", buy_chi=monthly_chi * 1.5, steps=2)

    out["buy_chi"] = round(out["buy_chi"], 2)
    out["sell_chi"] = round(out["sell_chi"], 2)
    return out


def market_decision(market: dict) -> str:
    """Market-only action code (no holdings, so rule 1 cannot apply). Used by the Claude task."""
    return decide(market)["action"]


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "market.json"
    m = json.loads(path.read_text())
    d = decide(m)
    print(json.dumps({"market_decision": d["action"], "rule": d["rule"], "above_200": round(d["above_200"], 4), "from_high": round(d["from_high"], 4)}))
