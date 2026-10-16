"""Fetch the world gold price, moving averages and USD/KHR -> data/market.json + data/history.csv.

Gold: COMEX gold futures (GC=F) daily bars from Yahoo Finance's public chart endpoint (no key).
USD/KHR: open.er-api.com, with a second free source as backup. Standard library only.
"""
import csv
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from decide import CHI_PER_OZ

ROOT = Path(__file__).resolve().parent.parent
MARKET_JSON = ROOT / "data" / "market.json"
HISTORY_CSV = ROOT / "data" / "history.csv"
UA = {"User-Agent": "Mozilla/5.0 (compatible; gold-cambodia-bot)"}
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range={rng}&interval=1d"

try:
    from zoneinfo import ZoneInfo

    PP = ZoneInfo("Asia/Phnom_Penh")
except Exception:  # tzdata missing: Cambodia has no DST, so a fixed +7 offset is exact
    PP = timezone(timedelta(hours=7))


def now_pp() -> datetime:
    return datetime.now(PP)


def http_json(url: str, tries: int = 3, timeout: int = 25):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"request failed: {type(last).__name__}")


def parse_chart(payload: dict) -> tuple[list[dict], float | None]:
    """Yahoo chart JSON -> (daily rows, latest price)."""
    res = payload["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(res["timestamp"]):
        o, h, l, c = (q[k][i] for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c):
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        rows.append({"date": d, "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2)})
    last = res.get("meta", {}).get("regularMarketPrice")
    return rows, (float(last) if last else None)


def fetch_history(rng: str = "5y") -> tuple[list[dict], float | None]:
    return parse_chart(http_json(YAHOO.format(rng=rng)))


def fetch_spot() -> float | None:
    """Latest gold price for alert checks; None if the source is unreachable."""
    try:
        _, last = parse_chart(http_json(YAHOO.format(rng="1d"), tries=1, timeout=15))
        return last
    except Exception:
        return None


def fetch_khr() -> tuple[float | None, str]:
    for url, pick, name in (
        ("https://open.er-api.com/v6/latest/USD", lambda j: j["rates"]["KHR"], "open.er-api.com"),
        ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json", lambda j: j["usd"]["khr"], "currency-api"),
    ):
        try:
            v = float(pick(http_json(url, tries=2)))
            if 3000 < v < 5500:  # sanity: the riel has traded near 4,000 per dollar for years
                return v, name
        except Exception:
            continue
    return None, ""


def mean_last(closes: list[float], n: int) -> float | None:
    return round(statistics.fmean(closes[-n:]), 2) if len(closes) >= n else None


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2)


def build_market(rows: list[dict], last_price: float | None, khr: float | None, khr_src: str, prev: dict | None, now: datetime) -> dict:
    today = now.date().isoformat()
    rows = [dict(r) for r in rows]
    if last_price:
        if rows and rows[-1]["date"] == today:
            rows[-1]["close"] = round(last_price, 2)
            rows[-1]["high"] = max(rows[-1]["high"], round(last_price, 2))
            rows[-1]["low"] = min(rows[-1]["low"], round(last_price, 2))
    closes = [r["close"] for r in rows]
    if len(closes) < 200:
        raise RuntimeError("not enough price history for the 200-day average")
    price = round(last_price or closes[-1], 2)
    if not 100 < price < 100000:
        raise RuntimeError("gold price failed the sanity check")

    cutoff = (datetime.fromisoformat(rows[-1]["date"]) - timedelta(days=92)).date().isoformat()
    recent = [r["close"] for r in rows if r["date"] >= cutoff]
    ma200 = mean_last(closes, 200)
    high3m = max(recent)

    if khr is None:
        khr, khr_src = (prev or {}).get("usd_khr", 4000.0), (prev or {}).get("khr_source", "") or "fallback (estimate)"

    def back(n: int) -> float | None:
        return pct(price, closes[-1 - n]) if len(closes) > n else None

    return {
        "asof": now.isoformat(timespec="minutes"),
        "date": today,
        "price_oz": price,
        "price_chi": round(price / CHI_PER_OZ, 2),
        "usd_khr": round(khr, 2),
        "khr_source": khr_src,
        "ma20": mean_last(closes, 20),
        "ma50": mean_last(closes, 50),
        "ma200": ma200,
        "high3m": round(high3m, 2),
        "low3m": round(min(recent), 2),
        "above_ma200_pct": pct(price, ma200),
        "from_high3m_pct": pct(price, high3m),
        "change_1d_pct": back(1),
        "change_1w_pct": back(5),
        "change_1m_pct": back(21),
        "source": "Yahoo Finance GC=F (COMEX gold futures, USD/oz); 1 chi = 3.75 g",
    }, rows


def write_outputs(market: dict, rows: list[dict]) -> None:
    MARKET_JSON.parent.mkdir(parents=True, exist_ok=True)
    MARKET_JSON.write_text(json.dumps(market, indent=2) + "\n")
    with HISTORY_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close"])
        for r in rows:
            w.writerow([r["date"], r["open"], r["high"], r["low"], r["close"]])


def main() -> int:
    try:
        rows, last = fetch_history()
        khr, src = fetch_khr()
        prev = json.loads(MARKET_JSON.read_text()) if MARKET_JSON.exists() else None
        market, rows = build_market(rows, last, khr, src, prev, now_pp())
    except Exception as exc:
        print(f"market update failed: {exc}")
        return 1
    write_outputs(market, rows)
    print(f"market updated: {market['date']} {market['price_oz']} USD/oz, {len(rows)} daily rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
