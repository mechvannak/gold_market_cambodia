"""Hourly delivery: send queued weekly/monthly reports once the chosen hour is reached,
and check price alerts. Messages go to the outbox; telegram_sync.py flush sends them
after the vault change is pushed."""
import sys
from datetime import datetime

import tg
import vault as vlt
from compose import bi, load_json, money, num, render
from decide import oz_to_chi
from market import MARKET_JSON, fetch_spot, now_pp

KEEP_REPORTS = 30


def deliver_queue(v: dict, now: datetime) -> int:
    if not v["owner_chat_id"] or not v["queue"] or now.hour < v["settings"]["hour"]:
        return 0
    sent = 0
    for rep in v["queue"]:
        tg.queue_message(v["owner_chat_id"], render(rep, v["settings"]["lang"]))
        rep["delivered"] = now.isoformat(timespec="minutes")
        v["reports"].append(rep)
        sent += 1
    v["queue"] = []
    v["reports"] = v["reports"][-KEEP_REPORTS:]
    return sent


def check_alerts(v: dict, price_oz: float, now: datetime) -> int:
    if not v["owner_chat_id"]:
        return 0
    price_chi = oz_to_chi(price_oz)
    fired = 0
    for a in v["alerts"]:
        if a.get("fired"):
            continue
        cur = price_chi if a["unit"] == "chi" else price_oz
        hit = cur <= a["level"] if a["dir"] == "below" else cur >= a["level"]
        if not hit:
            continue
        a["fired"] = now.isoformat(timespec="minutes")
        unit = "$/chi" if a["unit"] == "chi" else "$/oz"
        en = (
            f"🔔 Gold alert: price is {money(price_oz)}/oz ({money(price_chi)}/chi), "
            f"{'at or below' if a['dir'] == 'below' else 'at or above'} your level {num(a['level'])} {unit}.\n"
            "This alert will not repeat. Set a new one with /alert."
        )
        km = (
            f"🔔 ការជូនដំណឹងមាស៖ តម្លៃ {money(price_oz)}/អោន ({money(price_chi)}/ជី) "
            f"{'ក្រោម ឬស្មើ' if a['dir'] == 'below' else 'លើស ឬស្មើ'}កម្រិតរបស់អ្នក {num(a['level'])} {unit}។\n"
            "ការជូនដំណឹងនេះនឹងមិនត្រូវបានបន្តទេ។ កំណត់ថ្មីដោយប្រើ /alert។"
        )
        tg.queue_message(v["owner_chat_id"], bi(v["settings"]["lang"], en, km))
        fired += 1
    return fired


def main() -> int:
    try:
        v = vlt.load()
    except vlt.VaultError as exc:
        print(f"error: {exc}")
        return 1
    now = now_pp()
    market = load_json(MARKET_JSON)
    changed = deliver_queue(v, now)
    if any(not a.get("fired") for a in v["alerts"]):
        spot = fetch_spot() or (market or {}).get("price_oz")
        if spot:
            changed += check_alerts(v, float(spot), now)
    if changed:
        vlt.save(v)
    print(f"delivery: {changed} change(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
