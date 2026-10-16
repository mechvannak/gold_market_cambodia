"""Validate data/analysis.json before it is pushed.

  python scripts/check_analysis.py [path]      exit 0 = fine, exit 1 = problems listed

The report builder (compose.py) treats this file as untrusted data, but a malformed file would
silently produce a poor report, so the Claude task runs this check first.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from compose import load_json
from decide import ACTIONS
from market import ROOT, now_pp

ANALYSIS_JSON = ROOT / "data" / "analysis.json"
MODES = ("weekly", "monthly", "watchdog")
LEVELS = ("low", "medium", "high")
MAX_TEXT = 320  # compose.clean() cuts anything longer
MAX_AGE = timedelta(hours=3)


def _text_list(a: dict, key: str, problems: list[str]) -> list:
    v = a.get(key)
    if not isinstance(v, list) or not 1 <= len(v) <= 4:
        problems.append(f"{key} must be a list of 1-4 short strings")
        return []
    for i, x in enumerate(v):
        if not isinstance(x, str) or not x.strip():
            problems.append(f"{key}[{i}] must be a non-empty string")
        elif len(x) > MAX_TEXT:
            problems.append(f"{key}[{i}] is longer than {MAX_TEXT} characters")
    return v


def validate(a, now: datetime, check_age: bool = True) -> list[str]:
    if not isinstance(a, dict):
        return ["analysis must be a JSON object"]
    problems: list[str] = []

    try:
        ts = datetime.fromisoformat(str(a.get("generated_at", "")))
        if ts.tzinfo is None:
            problems.append("generated_at needs a timezone offset, e.g. 2026-10-19T07:58:00+07:00")
        else:
            if ts > now + timedelta(minutes=10):
                problems.append("generated_at is in the future")
            if check_age and now - ts > MAX_AGE:
                problems.append("generated_at is more than 3 hours old: use the real current time")
    except ValueError:
        problems.append("generated_at must be an ISO-8601 timestamp with timezone offset")

    mode = a.get("mode")
    if mode not in MODES:
        problems.append(f"mode must be one of {MODES}")
    if not isinstance(a.get("notify"), bool):
        problems.append("notify must be true or false")
    elif mode in ("weekly", "monthly") and a["notify"] is not True:
        problems.append("weekly and monthly analyses must have notify true")
    if a.get("confidence") not in LEVELS:
        problems.append(f"confidence must be one of {LEVELS}")
    if not isinstance(a.get("soften"), bool):
        problems.append("soften must be true or false")
    if a.get("market_decision") not in ACTIONS:
        problems.append(f"market_decision must be one of {ACTIONS} (take it from scripts/task_context.py)")
    price = a.get("price_at")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
        problems.append("price_at must be the positive gold price in USD/oz from data/market.json")

    for key in ("summary_en", "summary_km"):
        v = a.get(key)
        if not isinstance(v, str) or not v.strip():
            problems.append(f"{key} must be a non-empty string")
        elif len(v) > MAX_TEXT:
            problems.append(f"{key} is longer than {MAX_TEXT} characters")
    en, km = _text_list(a, "reasons_en", problems), _text_list(a, "reasons_km", problems)
    if en and km and len(en) != len(km):
        problems.append("reasons_en and reasons_km must have the same number of items")

    outlook = a.get("outlook")
    if outlook is not None:
        if not isinstance(outlook, dict):
            problems.append("outlook must be an object")
        else:
            for k in ("week", "month", "year"):
                for lang in ("en", "km"):
                    v = outlook.get(k, {}).get(lang) if isinstance(outlook.get(k), dict) else None
                    if not isinstance(v, str) or not v.strip() or len(v) > MAX_TEXT:
                        problems.append(f"outlook.{k}.{lang} must be a non-empty string up to {MAX_TEXT} characters")

    sources = a.get("sources")
    if sources is not None:
        if not isinstance(sources, list) or len(sources) > 8:
            problems.append("sources must be a list of at most 8 items")
        else:
            for i, s in enumerate(sources):
                ok = isinstance(s, dict) and isinstance(s.get("title"), str) and str(s.get("url", "")).startswith("https://")
                if not ok:
                    problems.append(f"sources[{i}] needs a title and an https:// url")
    return problems


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ANALYSIS_JSON
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read {path.name}: {type(exc).__name__}")
        return 1
    problems = validate(data, now_pp())
    for p in problems:
        print(f"- {p}")
    print("analysis OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
