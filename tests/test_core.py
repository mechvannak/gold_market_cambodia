import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import validate_init_data  # noqa: E402
from app.forecast import compute_forecast  # noqa: E402
from app.llm import _keyword_score  # noqa: E402


def make_df(n=260, start=2400.0, drift=0.0015, vol=0.008, seed=1):
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(drift, vol, n))
    idx = pd.date_range("2025-10-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Close": close, "High": close * 1.006, "Low": close * 0.994, "Open": close}, index=idx
    )


def macro(dxy_move, y_move, vix_move):
    def series(last_move):
        c = np.full(30, 100.0)
        c[-1] = 100.0 * (1 + last_move / 100)
        c[-6:-1] = 100.0
        return pd.DataFrame({"Close": c}, index=pd.date_range("2026-09-01", periods=30, freq="B"))

    return {"dxy": series(dxy_move), "us10y": series(y_move), "vix": series(vix_move)}


def news(score):
    return {"score": score, "summary": "s", "drivers": [], "method": "test", "n_items": 5}


def test_bullish_levels_are_ordered():
    fc = compute_forecast(make_df(), macro(-1.5, -5, 15), news(0.8))
    lv = fc["levels"]
    assert fc["bias"] == "bullish"
    assert lv["stop"] < lv["buy_zone"][0] < lv["buy_zone"][1] < fc["price"] < lv["sell_zone"][0] < lv["sell_zone"][1]


def test_bearish_flips_bias_and_pushes_buy_zone_deeper():
    d = make_df(drift=-0.0015)
    bull = compute_forecast(d, macro(-1.5, -5, 15), news(0.9))
    bear = compute_forecast(d, macro(1.5, 5, -15), news(-0.9))
    assert bear["bias"] == "bearish"
    assert bear["levels"]["buy_zone"][1] < bull["levels"]["buy_zone"][1]
    assert bear["levels"]["sell_zone"][1] < bull["levels"]["sell_zone"][1]


def test_scores_bounded_and_horizons_widen():
    fc = compute_forecast(make_df(), macro(0, 0, 0), news(0.0))
    assert -1 <= fc["composite"] <= 1
    h = fc["horizons"]
    assert (h["1m"]["high"] - h["1m"]["low"]) > (h["1w"]["high"] - h["1w"]["low"]) > (h["1d"]["high"] - h["1d"]["low"])
    assert len(fc["history"]["close"]) == 90


def test_missing_macro_data_does_not_break():
    fc = compute_forecast(make_df(), {}, news(0.3))
    assert fc["scores"]["macro"] == 0.0


def test_keyword_fallback_direction():
    bull = [{"title": "Fed rate cut hopes lift gold as dollar falls", "source": "x"}] * 8
    bear = [{"title": "Gold falls as yields rise on hawkish Fed", "source": "x"}] * 8
    assert _keyword_score(bull)["score"] > 0
    assert _keyword_score(bear)["score"] < 0


def _signed_init_data(token, user, age=0):
    fields = {"auth_date": str(int(time.time()) - age), "user": json.dumps(user), "query_id": "AAA"}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_init_data_valid_tampered_and_expired():
    token = "123:ABC"
    good = _signed_init_data(token, {"id": 42, "first_name": "A"})
    assert validate_init_data(good, token)["id"] == 42
    assert validate_init_data(good, "999:WRONG") is None
    assert validate_init_data(good.replace("42", "43"), token) is None
    assert validate_init_data(_signed_init_data(token, {"id": 1}, age=999999), token) is None
    assert validate_init_data("", token) is None
