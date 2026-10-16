"""Bot brain.

  python scripts/telegram_sync.py          read new bot messages / mini-app forms, apply commands, queue replies
  python scripts/telegram_sync.py send     turn data/analysis.json into a report (used by send.yml)
  python scripts/telegram_sync.py flush    send queued messages (run AFTER the vault change is pushed)

Only the owner chat (the first chat that sends /start) is obeyed. Logs never contain amounts,
chat ids or tokens.
"""
import math
import os
import re
import sys
from datetime import datetime

import tg
import vault as vlt
from compose import bi, build_report, load_json, money, num, render
from decide import holdings, oz_to_chi
from market import MARKET_JSON, ROOT, now_pp

ANALYSIS_JSON = ROOT / "data" / "analysis.json"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FORM_LINES = 20
KEEP_REPORTS = 30

HELP = (
    "/buy 2 400 [date]   bought 2 chi at $400/chi\n"
    "/sell 3 410         sold 3 chi at $410/chi\n"
    "/shop 510 503       shop sell / buyback price per chi\n"
    "/monthly 1          monthly buy amount in chi\n"
    "/lang km|en|both    report language\n"
    "/alert below 4000   price alert in $/oz (add 'chi' for $/chi); /alert clear\n"
    "/alerts             show alert settings\n"
    "/time 9             report delivery hour (8-20)\n"
    "/notify weekly off  turn weekly | monthly | watchdog reports on/off\n"
    "/help"
)


def _num(tok: str) -> float | None:
    try:
        x = float(tok.replace(",", "").lstrip("$"))
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _lang(v: dict) -> str:
    return v["settings"]["lang"]


def _bad(v: dict, usage: str) -> str:
    return bi(_lang(v), f"❌ Please use: {usage}", f"❌ សូមប្រើ៖ {usage}")


def _trade(v: dict, kind: str, args: list[str], today: str, market: dict | None) -> str:
    L = _lang(v)
    usage = f"/{kind} 2 400 [YYYY-MM-DD]"
    if len(args) < 2:
        return _bad(v, usage)
    chi, price = _num(args[0]), _num(args[1])
    date = args[2] if len(args) > 2 else today
    if chi is None or price is None or not 0 < chi <= 10000 or not 0 < price <= 100000:
        return _bad(v, usage)
    if not DATE_RE.match(date) or date > today:
        return bi(L, "❌ Date must be YYYY-MM-DD and not in the future.", "❌ កាលបរិច្ឆេទត្រូវជា YYYY-MM-DD ហើយមិនមែនអនាគតទេ។")
    before = holdings(v["purchases"])
    if kind == "sell" and chi > before["chi"] + 1e-9:
        return bi(L, f"❌ You only hold {num(before['chi'])} chi.", f"❌ អ្នកមានមាសត្រឹមតែ {num(before['chi'])} ជីប៉ុណ្ណោះ។")
    v["purchases"].append({"id": max((p["id"] for p in v["purchases"]), default=0) + 1, "type": kind, "chi": chi, "price": price, "date": date})
    after = holdings(v["purchases"])

    warn_en = warn_km = ""
    if market and price > 3 * oz_to_chi(market["price_oz"]):
        warn_en = "\n⚠️ That price looks like $/oz. This command expects $/chi."
        warn_km = "\n⚠️ តម្លៃនេះមើលទៅដូចជា $/អោន។ ពាក្យបញ្ជានេះត្រូវការ $/ជី។"
    if kind == "buy":
        en = f"✅ Bought {num(chi)} chi at {money(price)}/chi on {date}. You now hold {num(after['chi'])} chi, average cost {money(after['avg_cost'])}/chi.{warn_en}"
        km = f"✅ បានទិញ {num(chi)} ជី តម្លៃ {money(price)}/ជី ថ្ងៃ {date}។ ឥឡូវអ្នកមាន {num(after['chi'])} ជី ថ្លៃដើមមធ្យម {money(after['avg_cost'])}/ជី។{warn_km}"
    else:
        gain = after["realized"] - before["realized"]
        en = f"✅ Sold {num(chi)} chi at {money(price)}/chi on {date}. Realized {gain:+,.0f} USD. You now hold {num(after['chi'])} chi.{warn_en}"
        km = f"✅ បានលក់ {num(chi)} ជី តម្លៃ {money(price)}/ជី ថ្ងៃ {date}។ ចំណេញ/ខាតជាក់ស្តែង {gain:+,.0f} ដុល្លារ។ ឥឡូវអ្នកមាន {num(after['chi'])} ជី។{warn_km}"
    return bi(L, en, km)


def _alerts_text(v: dict) -> str:
    L, s = _lang(v), v["settings"]
    n = s["notify"]
    onoff = lambda b: "on" if b else "off"
    lines_en = [
        f"Language: {L} · report time {s['hour']}:00 · monthly buy {num(s['monthly_chi'])} chi",
        f"Reports: weekly {onoff(n['weekly'])}, monthly {onoff(n['monthly'])}, watchdog {onoff(n['watchdog'])}",
    ]
    lines_km = [
        f"ភាសា៖ {L} · ម៉ោងផ្ញើរបាយការណ៍ {s['hour']}:00 · ទិញប្រចាំខែ {num(s['monthly_chi'])} ជី",
        f"របាយការណ៍៖ ប្រចាំសប្ដាហ៍ {onoff(n['weekly'])}, ប្រចាំខែ {onoff(n['monthly'])}, ពិសេស {onoff(n['watchdog'])}",
    ]
    if v["alerts"]:
        for a in v["alerts"]:
            unit = "$/chi" if a["unit"] == "chi" else "$/oz"
            mark = " (fired)" if a.get("fired") else ""
            lines_en.append(f"🔔 {a['dir']} {num(a['level'])} {unit}{mark}")
            lines_km.append(f"🔔 {'ក្រោម' if a['dir'] == 'below' else 'លើស'} {num(a['level'])} {unit}{' (បានជូនដំណឹងរួច)' if a.get('fired') else ''}")
    else:
        lines_en.append("No price alerts set.")
        lines_km.append("មិនទាន់មានការជូនដំណឹងតម្លៃទេ។")
    return bi(L, "\n".join(lines_en), "\n".join(lines_km))


def apply_command(v: dict, line: str, today: str, market: dict | None = None) -> str:
    parts = line.strip().split()
    if not parts:
        return ""
    cmd, args = parts[0].lstrip("/").split("@")[0].lower(), parts[1:]
    L = _lang(v)
    s = v["settings"]

    if cmd in ("buy", "sell"):
        return _trade(v, cmd, args, today, market)

    if cmd == "shop":
        sell, buy = (_num(a) for a in args[:2]) if len(args) >= 2 else (None, None)
        if sell is None or buy is None or not 0 < buy <= sell <= 100000:
            return _bad(v, "/shop 510 503  (shop sell price, then shop buyback price, $/chi; buyback must not be higher)")
        v["shop"] = {"sell": sell, "buyback": buy, "date": today}
        return bi(L, f"✅ Shop prices saved: sell {money(sell)}, buyback {money(buy)} per chi.", f"✅ បានរក្សាទុកតម្លៃហាង៖ លក់ {money(sell)}, ទិញចូល {money(buy)} ក្នុងមួយជី។")

    if cmd == "monthly":
        n = _num(args[0]) if args else None
        if n is None or not 0 < n <= 1000:
            return _bad(v, "/monthly 1")
        s["monthly_chi"] = n
        return bi(L, f"✅ Monthly buy set to {num(n)} chi.", f"✅ កំណត់ការទិញប្រចាំខែ {num(n)} ជី។")

    if cmd == "lang":
        if not args or args[0].lower() not in ("km", "en", "both"):
            return _bad(v, "/lang km|en|both")
        s["lang"] = args[0].lower()
        return bi(s["lang"], f"✅ Language: {s['lang']}.", f"✅ ភាសា៖ {s['lang']}។")

    if cmd == "time":
        h = _num(args[0]) if args else None
        if h is None or h != int(h) or not 8 <= h <= 20:
            return _bad(v, "/time 9  (hour 8-20, Cambodia time)")
        s["hour"] = int(h)
        return bi(L, f"✅ Reports will arrive at {int(h)}:00 Cambodia time (within about an hour).", f"✅ របាយការណ៍នឹងមកដល់ម៉ោង {int(h)}:00 ម៉ោងកម្ពុជា (ក្នុងរយៈពេលប្រមាណមួយម៉ោង)។")

    if cmd == "notify":
        if len(args) < 2 or args[0].lower() not in s["notify"] or args[1].lower() not in ("on", "off"):
            return _bad(v, "/notify weekly|monthly|watchdog on|off")
        s["notify"][args[0].lower()] = args[1].lower() == "on"
        return bi(L, f"✅ {args[0].lower()} reports {args[1].lower()}.", f"✅ របាយការណ៍ {args[0].lower()} {args[1].lower()}។")

    if cmd == "alert":
        if args and args[0].lower() == "clear":
            v["alerts"] = []
            return bi(L, "✅ All price alerts cleared.", "✅ បានលុបការជូនដំណឹងតម្លៃទាំងអស់។")
        lvl = _num(args[1]) if len(args) >= 2 else None
        if len(args) < 2 or args[0].lower() not in ("below", "above") or lvl is None or lvl <= 0:
            return _bad(v, "/alert below 4000  (or above; add 'chi' for $/chi)  ·  /alert clear")
        unit = "chi" if len(args) > 2 and args[2].lower() == "chi" else "oz"
        a = {"dir": args[0].lower(), "level": lvl, "unit": unit, "fired": False}
        if len(v["alerts"]) >= 10:
            return bi(L, "❌ Maximum 10 alerts. Use /alert clear first.", "❌ អតិបរមា 10 ការជូនដំណឹង។ សូមប្រើ /alert clear ជាមុន។")
        v["alerts"] = [x for x in v["alerts"] if (x["dir"], x["level"], x["unit"]) != (a["dir"], a["level"], a["unit"])] + [a]
        u = "$/chi" if unit == "chi" else "$/oz"
        return bi(L, f"✅ Alert set: {a['dir']} {num(lvl)} {u}. I check every hour and tell you once.", f"✅ បានកំណត់ការជូនដំណឹង៖ {'ក្រោម' if a['dir'] == 'below' else 'លើស'} {num(lvl)} {u}។ ខ្ញុំពិនិត្យរៀងរាល់ម៉ោង ហើយប្រាប់អ្នកម្តង។")

    if cmd == "alerts":
        return _alerts_text(v)

    if cmd in ("help", "start"):
        return bi(L, "Gold Cambodia commands:\n" + HELP, "ពាក្យបញ្ជា Gold Cambodia៖\n" + HELP)

    return bi(L, "Unknown command. Send /help.", "មិនស្គាល់ពាក្យបញ្ជា។ សូមផ្ញើ /help។")


def process_updates(v: dict, updates: list[dict], today: str, market: dict | None) -> int:
    handled = 0
    for u in updates:
        v["last_update_id"] = max(v["last_update_id"], int(u["update_id"]))
        msg = u.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            continue
        chat_id = msg["chat"]["id"]
        if "web_app_data" in msg:
            lines = str(msg["web_app_data"].get("data", "")).splitlines()[:MAX_FORM_LINES]
        else:
            lines = [str(msg.get("text", ""))]
        lines = [x for x in lines if x.strip().startswith("/")]
        if not lines:
            continue
        if v["owner_chat_id"] is None:
            if lines[0].split()[0].lstrip("/").split("@")[0].lower() != "start":
                continue
            v["owner_chat_id"] = chat_id
        elif chat_id != v["owner_chat_id"]:
            continue
        replies = [r for r in (apply_command(v, x, today, market) for x in lines) if r]
        if replies:
            first = lines[0].split()[0].lstrip("/").split("@")[0].lower()
            tg.queue_message(chat_id, "\n\n".join(replies), with_keyboard=first in ("start", "help"))
            handled += 1
    return handled


def run_sync() -> int:
    v = vlt.load()
    updates = tg.get_updates(v["last_update_id"] + 1)
    if not updates:
        print("no new messages")
        return 0
    market = load_json(MARKET_JSON)
    handled = process_updates(v, updates, now_pp().date().isoformat(), market)
    vlt.save(v)
    print(f"processed {len(updates)} updates, replied to {handled}")
    return 0


def run_send() -> int:
    """Turn data/analysis.json into a report. Weekly/monthly are queued for the delivery hour."""
    analysis = load_json(ANALYSIS_JSON)
    market = load_json(MARKET_JSON)
    if not analysis:
        # Normal before the Claude task has run for the first time: nothing to do, not an error.
        print("no analysis yet: nothing to send")
        return 0
    if not market:
        # Leave last_analysis_at untouched so the hourly catch-up sends the report once market data exists.
        print("::warning title=Gold Cambodia::data/market.json is missing; run the market workflow")
        return 0
    v = vlt.load()
    stamp = str(analysis.get("generated_at", ""))
    if not stamp or stamp == v["last_analysis_at"]:
        print("analysis already handled")
        return 0
    kind = str(analysis.get("mode", "")).lower()
    v["last_analysis_at"] = stamp
    if kind not in ("weekly", "monthly", "watchdog"):
        vlt.save(v)
        print("no report requested")
        return 0
    if kind == "watchdog" and not analysis.get("notify"):
        vlt.save(v)
        print("watchdog: nothing to report")
        return 0
    if not v["settings"]["notify"].get(kind, True):
        vlt.save(v)
        print(f"{kind} reports are switched off")
        return 0

    now = now_pp()
    report = build_report(kind, market, analysis, v, now)
    report["id"] = max((r.get("id", 0) for r in v["reports"] + v["queue"]), default=0) + 1
    if kind == "watchdog" and v["owner_chat_id"]:
        report["delivered"] = now.isoformat(timespec="minutes")
        v["reports"].append(report)
        tg.queue_message(v["owner_chat_id"], render(report, _lang(v)))
    else:
        v["queue"].append(report)
    v["reports"] = v["reports"][-KEEP_REPORTS:]
    vlt.save(v)
    print(f"{kind} report {'sent' if kind == 'watchdog' else 'queued'}")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "sync"
    try:
        if mode == "flush":
            sent, failed = tg.flush_outbox()
            print(f"sent {sent}, failed {failed}")
            return 0
        if mode == "send":
            return run_send()
        return run_sync()
    except (vlt.VaultError, tg.TgError) as exc:
        print(f"error: {exc}")
        print(f"::error title=Gold Cambodia::{exc}")  # shows in the run summary; messages never hold secrets
        return 1
    except Exception as exc:  # unexpected: report only the type, never the message (it could echo data)
        print(f"::error title=Gold Cambodia::unexpected {type(exc).__name__} in telegram_sync.py")
        raise


if __name__ == "__main__":
    sys.exit(main())
