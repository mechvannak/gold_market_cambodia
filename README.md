# Gold Cambodia Price

A long-term advisor for buying and selling **physical gold in Cambodia**. Prices in **$/oz** and **$/chi**
(1 chi = 3.75 g), plus USD/KHR. The horizon is weekly, monthly and yearly: no day trading, no stop-loss,
no take-profit. The goal is to buy low and sell high, with Claude explaining the reasons.

Everything runs on GitHub (Actions + Pages) and one Claude scheduled task. **There is no server.**

Mini app: <https://mechvannak.github.io/gold_market_cambodia/>

> Educational tool, not financial advice. Gold prices can move sharply. The rules below are simple and
> have not been back-tested for profit.

## How it works

```
Claude scheduled task "Gold Market Cambodia"   Mon–Fri ~07:55 and ~20:55 (Phnom Penh)
   reads data/market.json + current news, follows CLAUDE_TASK.md
   writes data/analysis.json (English + Khmer) ──push──┐
                                                       ▼
GitHub Actions                                    send.yml  → report → Telegram (queued until your hour)
   market.yml  Mon–Fri 07:15 / 20:15  → data/market.json, data/history.csv
   sync.yml    hourly 07:05–22:05     → reads bot messages + mini-app forms, replies,
                                         delivers queued reports, checks price alerts
Telegram bot  ◄──── you: /buy, /sell, /shop … or the mini app forms
Mini app (index.html on GitHub Pages) ── unlocks data/private.enc in your browser
```

| Public files | Private file |
|--------------|--------------|
| `data/market.json`, `data/history.csv`, `data/analysis.json` | `data/private.enc` (holdings, purchases, alerts, settings, reports) |

`data/private.enc` is encrypted with **AES-256-GCM**, using a key derived from `VAULT_PASSPHRASE` with
**PBKDF2-SHA256 (600,000 iterations)**. The Actions scripts and the mini app (WebCrypto) use the same
format. Claude never sees the vault, the secrets or your personal data.

## Decision rules (`scripts/decide.py`, first match wins)

| # | Condition | Action |
|---|-----------|--------|
| 1 | Profit ≥ 50% **and** gold ≥ 20% above its 200-day average | **Sell in steps** (3 steps; always keep a 30% core) |
| 2 | Gold ≥ 25% above its 200-day average | **Reduce** (sell 15% of holdings, never into the core; no new buying) |
| 3 | Gold ≥ 15% above | **Wait** (buy half the monthly amount) |
| 4 | Gold ≥ 8% below its 3-month high, or below its 200-day average | **Buy extra** (1.5× monthly, 2 steps) / **buy in steps** (2× monthly, 3 steps) |
| 5 | Otherwise | **Hold / normal monthly buy** |

Profit is measured against the shop buyback price if you have set it with `/shop`, otherwise against the
world price converted to $/chi. Claude's news analysis sets the **confidence** and may **soften** a plan
(halve the size). It can never flip the decision.

## One-time setup

1. **Repository secrets** (Settings → Secrets and variables → Actions): `TELEGRAM_TOKEN` (from
   [@BotFather](https://t.me/BotFather)) and `VAULT_PASSPHRASE`.
   - Use a long passphrase: at least 12 characters, ideally 4+ random words. The repository is public, so
     anyone can download `private.enc` and try to guess the passphrase offline; a long passphrase is what
     protects your holdings.
   - Secrets live **only** in GitHub secrets: never in code, prompts, issues or chat.
2. **Pages**: Settings → Pages → Deploy from a branch → `main` / `(root)`.
3. **Actions billing**: Actions needs a working GitHub billing / spending limit, or jobs are not started.
4. **First data run**: Actions → `market` → *Run workflow*. This creates `data/market.json` and
   `data/history.csv`. Check the run is green (the price source is Yahoo Finance; if it ever refuses the
   runner, the job fails visibly and the old data stays).
5. **Claude scheduled task** "Gold Market Cambodia": Mon–Fri ~07:55 and ~20:55 Asia/Phnom_Penh, with the
   prompt: *"Follow CLAUDE_TASK.md in the repository mechvannak/gold_market_cambodia."* The task needs
   permission to push `data/analysis.json` to `main`.
6. **Pair the bot**: open your bot in Telegram and send **`/start` straight away**. The first chat that
   sends `/start` becomes the owner and all other chats are ignored. The bot answers at the next hourly
   sync (or run Actions → `sync` → *Run workflow*).

## Using the bot

```
/buy 2 400 [date]     bought 2 chi at $400/chi
/sell 3 410           sold 3 chi at $410/chi
/shop 510 503         shop sell / buyback price per chi
/monthly 1            monthly buy amount in chi
/lang km|en|both      report language
/alert below 4000     price alert in $/oz (add 'chi' for $/chi); /alert clear
/alerts               show alert settings
/time 9               report delivery hour (8-20)
/notify weekly off    turn weekly | monthly | watchdog reports on/off
/help
```

The bot answers within about an hour (it reads messages when `sync.yml` runs). Weekly and monthly
reports are queued until your chosen hour; watchdog alerts are sent straight away.

## Using the mini app

- **Home, Chart**: public. Price, where it sits against its 200-day average and 3-month high, the price
  rules' decision, and Claude's reasons. The chart has 1W / 1M / 3M / 6M / 1Y / custom ranges, daily or
  weekly bars, and a tooltip.
- **My gold, Alerts**: unlock with your passphrase (checked in your browser only). Optional Face ID /
  fingerprint unlock through Telegram's BiometricManager; this stores the passphrase in Telegram's secure
  storage on that device.
- **Forms** (trades, shop prices, alert and report settings) send commands back to the bot with Telegram
  `sendData`. Telegram only allows that when the app is opened from the **“📊 Gold Cambodia” keyboard
  button** at the bottom of the bot chat (sent by `/start` and `/help`), not from the menu button. If the
  app is opened another way, it shows the command text to copy and send yourself.

## Files

```
index.html                 Telegram mini app (Khmer/English, Kantumruy Pro, sea blue + sky blue)
CLAUDE_TASK.md             instructions for the Claude scheduled task
data/                      market.json, history.csv, analysis.json (public) · private.enc (encrypted)
scripts/market.py          world gold price, 20/50/200-day averages, 3-month high, USD/KHR
scripts/decide.py          decision rules, holdings maths
scripts/compose.py         Khmer/English report builder
scripts/telegram_sync.py   reads bot messages + mini-app forms; builds and queues reports
scripts/deliver.py         delivers queued reports at your hour; price alerts
scripts/vault.py           AES-256-GCM / PBKDF2 vault
scripts/tg.py              Telegram helper; messages are sent only after the vault commit is pushed
scripts/task_context.py    mode / decision-change facts for the Claude task
scripts/check_analysis.py  validates data/analysis.json before it is pushed
scripts/git_push.sh        commit and push with retries
.github/workflows/         market.yml, send.yml, sync.yml
tests/                     python -m unittest discover -s tests   (needs: pip install cryptography; Node 18+)
```

## Privacy and safety

- Public: price data and Claude's analysis only. Never commit unencrypted personal data
  (`.gitignore` blocks `private.json` and `*.plain.json`).
- Workflow logs on a public repo are public, so the scripts never print holdings, amounts, chat ids or
  tokens. Keep it that way when you change them.
- If the passphrase is wrong, the scripts stop instead of overwriting the vault.
- Changing `VAULT_PASSPHRASE` makes the existing `private.enc` unreadable. To change it, decrypt with the
  old one and re-encrypt with the new one first.

## Notes and limits

- Gold price is COMEX futures (Yahoo Finance `GC=F`), not a Cambodian shop price. Shop prices differ by a
  margin; set them with `/shop` for a realistic profit figure.
- 1 chi = 3.75 g of pure gold. Local purity and shop margins are not modelled.
- Khmer wording was written for clarity; please have a native speaker review it and adjust to the terms
  you prefer.
