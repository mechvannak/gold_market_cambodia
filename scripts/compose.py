"""Build the Khmer/English report from market data, Claude's analysis and the private vault."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from decide import decide, holdings, oz_to_chi

ROOT = Path(__file__).resolve().parent.parent
STALE_AFTER = timedelta(days=4)
SEP = "\n\n— — —\n\n"

LABEL = {
    "SELL_STEPS": ("SELL in steps", "លក់ជាជំហានៗ"),
    "REDUCE": ("REDUCE holdings", "កាត់បន្ថយមាសដែលកាន់"),
    "WAIT": ("WAIT (half the monthly buy)", "រង់ចាំ (ទិញពាក់កណ្ដាលនៃចំនួនប្រចាំខែ)"),
    "BUY_EXTRA": ("BUY EXTRA (price dipped)", "ទិញបន្ថែម (តម្លៃធ្លាក់ចុះ)"),
    "BUY_STEPS": ("BUY in steps (below 200-day average)", "ទិញជាជំហានៗ (ក្រោមមធ្យមភាគ 200 ថ្ងៃ)"),
    "HOLD": ("HOLD / normal monthly buy", "រក្សាទុក / ទិញធម្មតាប្រចាំខែ"),
}
KIND = {
    "weekly": ("Weekly report", "របាយការណ៍ប្រចាំសប្ដាហ៍"),
    "monthly": ("Monthly buy-day report", "របាយការណ៍ថ្ងៃទិញប្រចាំខែ"),
    "watchdog": ("Watchdog alert", "ការជូនដំណឹងពិសេស"),
}
CONF = {"high": ("high", "ខ្ពស់"), "medium": ("medium", "មធ្យម"), "low": ("low", "ទាប")}


def bi(lang: str, en: str, km: str) -> str:
    """Pick language: 'en', 'km', or both (Khmer first)."""
    return en if lang == "en" else km if lang == "km" else f"{km}\n{en}"


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def money(x: float) -> str:
    return f"${x:,.0f}" if abs(x) >= 1000 else f"${x:,.1f}"


def num(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def clean(text, limit: int = 320) -> str:
    """Analysis text is data: strip control characters and cap the length."""
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text)).strip()
    return s[:limit]


def analysis_info(analysis: dict | None, now: datetime) -> dict:
    a = analysis or {}
    fresh = False
    try:
        ts = datetime.fromisoformat(str(a.get("generated_at", "")))
        fresh = (now - ts.astimezone(now.tzinfo)) <= STALE_AFTER if ts.tzinfo else False
    except ValueError:
        pass
    conf = str(a.get("confidence", "medium")).lower()
    return {
        "fresh": fresh,
        "confidence": conf if conf in CONF and fresh else "low",
        "soften": bool(a.get("soften")) and fresh,
        "summary_en": clean(a.get("summary_en", "")),
        "summary_km": clean(a.get("summary_km", "")),
        "reasons_en": [clean(x) for x in (a.get("reasons_en") or [])][:4] if fresh else [],
        "reasons_km": [clean(x) for x in (a.get("reasons_km") or [])][:4] if fresh else [],
    }


def build_report(kind: str, market: dict, analysis: dict | None, vault: dict, now: datetime) -> dict:
    hold = holdings(vault["purchases"])
    price_chi = oz_to_chi(market["price_oz"])
    shop = vault.get("shop") or {}
    buyback = shop.get("buyback")
    ref_chi = float(buyback) if buyback else price_chi
    monthly = float(vault["settings"]["monthly_chi"])
    d = decide(market, hold, ref_chi, monthly)
    info = analysis_info(analysis, now)

    softened = False
    if info["soften"]:
        softened = True
        d["buy_chi"] = round(d["buy_chi"] * 0.5, 2)
        d["sell_chi"] = round(d["sell_chi"] * 0.5, 2)

    c = {
        "date": now.date().isoformat(),
        "oz": money(market["price_oz"]),
        "chi": money(price_chi),
        "khr": f"{round(price_chi * market['usd_khr'], -3):,.0f}",
        "above": market["above_ma200_pct"],
        "high": market["from_high3m_pct"],
        "b": num(d["buy_chi"]),
        "s": num(d["sell_chi"]),
        "m": num(monthly),
        "core": num(d["core_chi"]),
        "steps": d["steps"],
    }
    label_en, label_km = LABEL[d["action"]]
    t_en, t_km = KIND[kind]
    conf_en, conf_km = CONF[info["confidence"]]

    plan = {
        "SELL_STEPS": (
            f"Sell {c['s']} chi now, then repeat in {c['steps'] - 1} more steps (about 1 per week) while the price stays high. Keep at least {c['core']} chi as your core.",
            f"លក់ {c['s']} ជីឥឡូវនេះ ហើយធ្វើបន្តក្នុង {c['steps'] - 1} ជំហានទៀត (ប្រហែល 1 ជំហាន/សប្ដាហ៍) ប្រសិនបើតម្លៃនៅខ្ពស់។ រក្សាស្នូលយ៉ាងតិច {c['core']} ជី។",
        ),
        "REDUCE": (
            f"Sell {c['s']} chi. Keep at least {c['core']} chi as your core.",
            f"លក់ {c['s']} ជី។ រក្សាស្នូលយ៉ាងតិច {c['core']} ជី។",
        ),
        "WAIT": (
            f"Buy {c['b']} chi this month (half of {c['m']}).",
            f"ទិញ {c['b']} ជីក្នុងខែនេះ (ពាក់កណ្ដាលនៃ {c['m']} ជី)។",
        ),
        "BUY_EXTRA": (
            f"Buy {c['b']} chi this month in {c['steps']} steps.",
            f"ទិញ {c['b']} ជីក្នុងខែនេះ ជា {c['steps']} ជំហាន។",
        ),
        "BUY_STEPS": (
            f"Buy {c['b']} chi this month in {c['steps']} steps.",
            f"ទិញ {c['b']} ជីក្នុងខែនេះ ជា {c['steps']} ជំហាន។",
        ),
        "HOLD": (
            f"Buy the normal {c['b']} chi this month; otherwise hold.",
            f"ទិញតាមធម្មតា {c['b']} ជីក្នុងខែនេះ បើមិនដូច្នោះទេ រក្សាទុក។",
        ),
    }[d["action"]]

    if hold["chi"] > 0:
        value = hold["chi"] * ref_chi
        basis_en = "at shop buyback price" if buyback else "at world price, estimate"
        basis_km = "តាមតម្លៃហាងទិញចូល" if buyback else "តាមតម្លៃពិភពលោក (ប៉ាន់ស្មាន)"
        pr = f"{d['profit'] * 100:+.1f}%"
        own_en = f"Your gold: {num(hold['chi'])} chi · average cost {money(hold['avg_cost'])}/chi · value ≈ {money(value)} · profit {pr} ({basis_en})"
        own_km = f"មាសរបស់អ្នក៖ {num(hold['chi'])} ជី · ថ្លៃដើមមធ្យម {money(hold['avg_cost'])}/ជី · តម្លៃប្រហែល {money(value)} · ចំណេញ/ខាត {pr} ({basis_km})"
    else:
        own_en = "No holdings recorded yet. Add purchases with /buy."
        own_km = "មិនទាន់មានកំណត់ត្រាមាសទេ។ បន្ថែមការទិញដោយប្រើ /buy។"

    shop_en = shop_km = ""
    if shop.get("sell") or buyback:
        shop_en = f"\nShop: sell {money(float(shop['sell']))} / buyback {money(float(buyback))} per chi" if shop.get("sell") and buyback else ""
        shop_km = f"\nហាង៖ លក់ {money(float(shop['sell']))} / ទិញចូល {money(float(buyback))} ក្នុងមួយជី" if shop.get("sell") and buyback else ""

    soft_en = "\nClaude suggests a softer plan (half size) because of news or uncertainty." if softened else ""
    soft_km = "\nClaude ណែនាំឱ្យធ្វើផែនការស្រាលជាងមុន (ពាក់កណ្ដាល) ដោយសារព័ត៌មាន ឬភាពមិនប្រាកដប្រជា។" if softened else ""
    fresh_en = "" if info["fresh"] else "\nNo fresh Claude analysis yet; the decision below uses the price rules only."
    fresh_km = "" if info["fresh"] else "\nមិនទាន់មានការវិភាគថ្មីពី Claude ទេ ការសម្រេចនេះប្រើតែច្បាប់តម្លៃប៉ុណ្ណោះ។"

    why_en = "\n".join(f"• {x}" for x in info["reasons_en"]) or (f"• {info['summary_en']}" if info["summary_en"] else "")
    why_km = "\n".join(f"• {x}" for x in info["reasons_km"]) or (f"• {info['summary_km']}" if info["summary_km"] else "")

    en = (
        f"🥇 Gold Cambodia — {t_en} ({c['date']})\n\n"
        f"Price: {c['oz']}/oz = {c['chi']}/chi ≈ {c['khr']} KHR/chi\n"
        f"vs 200-day average: {c['above']:+.1f}% · vs 3-month high: {c['high']:+.1f}%{shop_en}\n\n"
        f"Decision: {label_en}\nPlan: {plan[0]}{soft_en}{fresh_en}\n\n{own_en}"
        + (f"\n\nWhy (Claude, confidence {conf_en}):\n{why_en}" if why_en else "")
        + "\n\n⚠️ Not financial advice. Gold prices can move sharply."
    )
    km = (
        f"🥇 មាសកម្ពុជា — {t_km} ({c['date']})\n\n"
        f"តម្លៃ៖ {c['oz']}/អោន = {c['chi']}/ជី ≈ {c['khr']} រៀល/ជី\n"
        f"ធៀបនឹងមធ្យមភាគ 200 ថ្ងៃ៖ {c['above']:+.1f}% · ធៀបនឹងកម្រិតខ្ពស់ 3 ខែ៖ {c['high']:+.1f}%{shop_km}\n\n"
        f"សេចក្តីសម្រេច៖ {label_km}\nផែនការ៖ {plan[1]}{soft_km}{fresh_km}\n\n{own_km}"
        + (f"\n\nហេតុផល (Claude, ទំនុកចិត្ត៖ {conf_km})៖\n{why_km}" if why_km else "")
        + "\n\n⚠️ នេះមិនមែនជាដំបូន្មានហិរញ្ញវត្ថុទេ។ តម្លៃមាសអាចប្រែប្រួលខ្លាំង។"
    )
    return {
        "kind": kind,
        "created": now.isoformat(timespec="minutes"),
        "action": d["action"],
        "rule": d["rule"],
        "price_oz": market["price_oz"],
        "text_en": en,
        "text_km": km,
    }


def render(report: dict, lang: str) -> str:
    if lang == "en":
        return report["text_en"]
    if lang == "km":
        return report["text_km"]
    return report["text_km"] + SEP + report["text_en"]
