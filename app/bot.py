import asyncio
import html
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo

from .config import settings
from .forecast import get_forecast

log = logging.getLogger("goldbot")
SUBS_FILE = Path(__file__).resolve().parent.parent / "subscribers.json"
dp = Dispatcher()


def _subs() -> set[int]:
    try:
        return set(json.loads(SUBS_FILE.read_text()))
    except Exception:
        return set()


def _save_subs(s: set[int]) -> None:
    SUBS_FILE.write_text(json.dumps(sorted(s)))


def _allowed(msg: Message) -> bool:
    return not settings.allowed_users or (msg.from_user and msg.from_user.id in settings.allowed_users)


def _app_markup() -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📈 Open gold dashboard", web_app=WebAppInfo(url=f"{settings.webapp_url}/app/"))]]
    )


def format_forecast(fc: dict) -> str:
    lv = fc["levels"]
    icon = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}[fc["bias"]]
    lines = [
        f"<b>🥇 Gold (XAU/USD) ${fc['price']:,.2f}</b>",
        f"{icon} Bias: <b>{fc['bias'].upper()}</b> · confidence {fc['confidence']} · score {fc['composite']:+.2f}",
        f"Action: <b>{html.escape(fc['action'])}</b>",
        "",
        f"Buy zone:  <b>${lv['buy_zone'][0]:,.0f} – ${lv['buy_zone'][1]:,.0f}</b>",
        f"Sell zone: <b>${lv['sell_zone'][0]:,.0f} – ${lv['sell_zone'][1]:,.0f}</b>",
        f"Stop-loss: ${lv['stop']:,.0f} · reward/risk {lv['reward_risk']}",
        "",
        f"1d ≈ ${fc['horizons']['1d']['expected']:,.0f} · 1w ≈ ${fc['horizons']['1w']['expected']:,.0f} · 1m ≈ ${fc['horizons']['1m']['expected']:,.0f}",
        "",
        html.escape(fc["news"]["summary"]),
    ]
    for d in fc["news"]["drivers"][:3]:
        arrow = "▲" if d["direction"] == "bullish" else "▼" if d["direction"] == "bearish" else "•"
        lines.append(f"{arrow} {html.escape(d['theme'])}")
    lines += ["", f"<i>{html.escape(fc['disclaimer'])}</i>"]
    return "\n".join(lines)


@dp.message(CommandStart())
async def start(msg: Message):
    if not _allowed(msg):
        return
    await msg.answer(
        "Hi! I forecast gold from world economic news, the dollar, yields and price action, "
        "and suggest buy / sell zones.\n\n"
        "/forecast – latest forecast\n/subscribe – daily morning forecast\n/unsubscribe – stop daily forecast",
        reply_markup=_app_markup(),
    )


@dp.message(Command("forecast"))
async def forecast_cmd(msg: Message):
    if not _allowed(msg):
        return
    wait = await msg.answer("Analysing the latest news and prices…")
    try:
        fc = await asyncio.to_thread(get_forecast)
        await wait.edit_text(format_forecast(fc), parse_mode="HTML", reply_markup=_app_markup())
    except Exception as exc:
        log.exception("forecast failed")
        await wait.edit_text(f"Sorry, I couldn't get the data right now ({type(exc).__name__}). Try again in a minute.")


@dp.message(Command("subscribe"))
async def subscribe(msg: Message):
    if not _allowed(msg):
        return
    s = _subs()
    s.add(msg.chat.id)
    _save_subs(s)
    await msg.answer(f"Subscribed. You'll get the forecast daily at {settings.alert_hour:02d}:00 ({settings.timezone}).")


@dp.message(Command("unsubscribe"))
async def unsubscribe(msg: Message):
    s = _subs()
    s.discard(msg.chat.id)
    _save_subs(s)
    await msg.answer("Unsubscribed.")


async def _alert_loop(bot: Bot):
    tz = ZoneInfo(settings.timezone)
    last_sent = None
    while True:
        await asyncio.sleep(60)
        now = datetime.now(tz)
        if now.hour != settings.alert_hour or last_sent == now.date():
            continue
        last_sent = now.date()
        subs = _subs()
        if not subs:
            continue
        try:
            fc = await asyncio.to_thread(get_forecast, True)
        except Exception:
            log.exception("daily forecast failed")
            continue
        text = format_forecast(fc)
        for chat_id in subs:
            try:
                await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=_app_markup())
            except Exception:
                log.warning("could not send to %s", chat_id)


async def run_bot():
    bot = Bot(settings.bot_token)
    if settings.webapp_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Gold", web_app=WebAppInfo(url=f"{settings.webapp_url}/app/"))
        )
    asyncio.create_task(_alert_loop(bot))
    await dp.start_polling(bot)
