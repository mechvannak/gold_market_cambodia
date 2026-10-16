"""Technical and macro scoring. Every score is in [-1, +1]; positive = bullish for gold."""
import numpy as np
import pandas as pd


def clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))


def rsi(close: pd.Series, n: int = 14) -> float:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    val = 100 - 100 / (1 + rs)
    return float(val.iloc[-1]) if not np.isnan(val.iloc[-1]) else 50.0


def atr(df: pd.DataFrame, n: int = 14) -> float:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def technicals(df: pd.DataFrame) -> dict:
    close = df["Close"]
    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
    r = rsi(close)
    a = atr(df)
    mom20 = price / float(close.iloc[-21]) - 1 if len(close) > 21 else 0.0
    support = float(df["Low"].tail(20).min())
    resistance = float(df["High"].tail(20).max())

    score = 0.0
    score += 0.30 * (1 if price > sma50 else -1)
    score += 0.25 * (1 if sma50 > sma200 else -1)
    score += 0.25 * clip(mom20 / 0.05)
    score += 0.20 * clip((r - 50) / 25)
    if r > 75:  # stretched: expect a pullback
        score -= 0.25
    elif r < 25:
        score += 0.25
    return {
        "score": round(clip(score), 3),
        "price": price,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "rsi": r,
        "atr": a,
        "mom20": mom20,
        "support": support,
        "resistance": resistance,
    }


def _chg(df: pd.DataFrame | None, days: int = 5) -> float | None:
    if df is None or len(df) <= days:
        return None
    c = df["Close"]
    return float(c.iloc[-1] / c.iloc[-1 - days] - 1) * 100


def macro_score(macro: dict[str, pd.DataFrame]) -> dict:
    """Weaker dollar, falling yields and rising fear support gold."""
    parts = {}
    dxy = _chg(macro.get("dxy"))
    y10 = _chg(macro.get("us10y"))
    vix = _chg(macro.get("vix"))
    if dxy is not None:
        parts["dxy"] = (clip(-dxy / 1.5), 0.45, dxy)
    if y10 is not None:
        parts["us10y"] = (clip(-y10 / 6.0), 0.40, y10)
    if vix is not None:
        parts["vix"] = (clip(vix / 25.0), 0.15, vix)
    if not parts:
        return {"score": 0.0, "components": {}}
    wsum = sum(w for _, w, _ in parts.values())
    score = sum(s * w for s, w, _ in parts.values()) / wsum
    return {
        "score": round(clip(score), 3),
        "components": {k: {"score": round(s, 3), "change_5d_pct": round(ch, 2)} for k, (s, _, ch) in parts.items()},
    }
