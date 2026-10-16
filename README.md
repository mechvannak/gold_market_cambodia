# Gold Forecast: Telegram bot + Mini App

Forecasts gold (XAU/USD) from world economic news, the US dollar, bond yields, market fear and price
action, then suggests **buy zone, sell zone and stop-loss**. Delivered through a Telegram bot with a
Mini App dashboard.

## How the forecast works

| Part | Weight | Source | What it measures |
|------|--------|--------|------------------|
| News | 40% | Google News / FXStreet RSS, scored by Claude | Whether recent headlines (Fed, inflation, war, central banks, oil...) are bullish or bearish for gold |
| Macro | 30% | Yahoo Finance: DXY, US 10y yield, VIX | Weaker dollar, falling yields, rising fear = bullish |
| Technical | 30% | Yahoo Finance: gold futures (GC=F) | Trend (50/200-day averages), 20-day momentum, RSI |

The three scores (-1 to +1) are blended into one composite. Bias is bullish above +0.2, bearish below -0.2.
Buy and sell zones are placed relative to the current price using ATR (typical daily range): a bullish
score pulls the buy zone closer and pushes the sell target farther; a bearish score does the opposite.
The stop sits below the buy zone.

> This is a rules-based model, not a crystal ball and not financial advice. It has not been
> back-tested for profitability. Paper-trade it first and never risk money you can't afford to lose.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Get a Claude API key from console.anthropic.com (optional but strongly recommended; without it a
   simple keyword scorer is used).
3. Install and configure:
   ```bash
   cd gold-bot
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env      # fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, WEBAPP_URL
   ```
4. Mini Apps need a public **HTTPS** URL. For testing, tunnel your local port:
   ```bash
   cloudflared tunnel --url http://localhost:8080   # or: ngrok http 8080
   ```
   Put the printed `https://...` address in `WEBAPP_URL` in `.env`.
5. Run:
   ```bash
   python main.py
   ```
6. Open your bot in Telegram, send `/start`, tap **Open gold dashboard**.

For permanent hosting, run `python main.py` on any small VPS / Railway / Fly.io / Render behind HTTPS.

## Bot commands

- `/start` : intro + button to open the Mini App (also set as the bot's menu button)
- `/forecast` : forecast as a chat message
- `/subscribe`, `/unsubscribe` : daily forecast at `ALERT_HOUR` in `TIMEZONE` (default 08:00 Asia/Bangkok)

## Security

- The API only answers requests carrying valid Telegram `initData` (signature checked with your bot
  token). Set `ALLOWED_USER_IDS` to restrict it to yourself/friends.
- `DEV_MODE=1` disables that check for local testing only. Never enable it in production.
- Keep `.env` private.

## Tuning

- Weights: `WEIGHTS` in `app/forecast.py`
- News sources: `QUERIES` / `FEEDS` in `app/news.py`
- Zone distances and stop: `compute_forecast` in `app/forecast.py`
- Run tests: `pytest`

## Project layout

```
main.py            runs API + bot together
app/data.py        market data (Yahoo Finance)
app/news.py        RSS headlines
app/llm.py         Claude news scoring (+ keyword fallback)
app/analysis.py    technical + macro scores
app/forecast.py    blending, buy/sell levels, horizons
app/api.py         FastAPI + serves the Mini App
app/auth.py        Telegram initData validation
app/bot.py         aiogram bot, commands, daily alerts
index.html         Mini App dashboard (served by the API at /app/)
docs/index.html    project landing page for GitHub Pages
```
