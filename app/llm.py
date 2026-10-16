"""Turn news headlines into a gold-price impact score using Claude (keyword fallback)."""
import json
import re

from .config import settings

SYSTEM = (
    "You are a macro analyst covering gold (XAU/USD). Given numbered news headlines, judge how each "
    "affects the gold price over the next days to weeks. Gold rises with: falling real yields, a weaker "
    "US dollar, rate-cut expectations, inflation worries, geopolitical or financial stress, central-bank "
    "buying. Gold falls with: higher yields, a stronger dollar, hawkish central banks, risk-on easing of "
    "tensions, profit-taking or ETF outflows. Ignore headlines unrelated to gold, rates, FX, inflation, "
    "growth or geopolitics. Reply with JSON only."
)

PROMPT = """Headlines:
{headlines}

Return JSON exactly in this shape:
{{
  "items": [{{"i": 1, "impact": -2..2, "relevance": 0..1}}],
  "summary": "2-3 sentence plain-language read of the news backdrop for gold",
  "key_drivers": [{{"theme": "short name", "direction": "bullish|bearish", "why": "one sentence"}}]
}}
impact: -2 strongly bearish for gold, 0 neutral, +2 strongly bullish. Give at most 5 key_drivers."""

BULL = [
    "rate cut", "cuts rates", "dovish", "safe haven", "safe-haven", "weaker dollar", "dollar falls",
    "dollar slips", "yields fall", "yields drop", "inflation rises", "inflation accelerat", "geopolitical",
    "tension", "war", "sanction", "central bank buy", "recession", "slowdown", "record high", "gold rises",
    "gold climbs", "gold jumps", "gold surges", "banking stress", "shutdown",
]
BEAR = [
    "rate hike", "hawkish", "stronger dollar", "dollar rises", "dollar surges", "yields rise", "yields jump",
    "gold falls", "gold slips", "gold drops", "gold declines", "profit-taking", "outflows", "ceasefire",
    "peace deal", "risk-on", "inflation cools", "strong jobs", "strong data",
]


def _keyword_score(items: list[dict]) -> dict:
    total = 0.0
    hits = 0
    drivers = []
    for it in items:
        t = it["title"].lower()
        b = sum(k in t for k in BULL)
        s = sum(k in t for k in BEAR)
        if b or s:
            hits += 1
            total += (b - s) / (b + s)
            if len(drivers) < 5:
                drivers.append(
                    {
                        "theme": it["title"][:70],
                        "direction": "bullish" if b > s else "bearish" if s > b else "mixed",
                        "why": "Keyword match (no Claude key configured).",
                    }
                )
    score = max(-1.0, min(1.0, total / max(hits, 1) * min(1.0, hits / 6)))
    return {
        "score": round(score, 3),
        "summary": f"Keyword scan of {len(items)} headlines ({hits} relevant). Add ANTHROPIC_API_KEY for a deeper read.",
        "drivers": drivers,
        "method": "keywords",
        "n_items": len(items),
    }


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in model reply")
    return json.loads(m.group(0))


def score_news(items: list[dict]) -> dict:
    if not items:
        return {"score": 0.0, "summary": "No fresh headlines found.", "drivers": [], "method": "none", "n_items": 0}
    if not settings.anthropic_key:
        return _keyword_score(items)
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_key)
        listing = "\n".join(f"{i}. {it['title']} ({it['source']})" for i, it in enumerate(items, 1))
        resp = client.messages.create(
            model=settings.model,
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role": "user", "content": PROMPT.format(headlines=listing)}],
        )
        data = _extract_json("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))
        num = den = 0.0
        for row in data.get("items", []):
            imp = max(-2.0, min(2.0, float(row.get("impact", 0))))
            rel = max(0.0, min(1.0, float(row.get("relevance", 0))))
            num += imp * rel
            den += rel
        confidence = min(1.0, den / 6.0)  # few relevant headlines -> shrink toward neutral
        score = (num / (2 * den) if den else 0.0) * confidence
        return {
            "score": round(max(-1.0, min(1.0, score)), 3),
            "summary": str(data.get("summary", "")).strip(),
            "drivers": [
                {
                    "theme": str(d.get("theme", ""))[:80],
                    "direction": str(d.get("direction", "")).lower(),
                    "why": str(d.get("why", ""))[:240],
                }
                for d in data.get("key_drivers", [])[:5]
            ],
            "method": "claude",
            "n_items": len(items),
        }
    except Exception as exc:  # network/API/parse problems: degrade, don't fail the forecast
        out = _keyword_score(items)
        out["summary"] = f"Claude scoring unavailable ({type(exc).__name__}); used keyword scan. " + out["summary"]
        return out
