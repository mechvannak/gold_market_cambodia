import asyncio
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .auth import validate_init_data
from .config import settings
from .forecast import get_forecast

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"

app = FastAPI(title="Gold forecast")
_lock = asyncio.Lock()


def _check_user(init_data: str | None) -> dict:
    if settings.dev_mode:
        return {"id": 0, "first_name": "dev"}
    user = validate_init_data(init_data or "", settings.bot_token)
    if user is None:
        raise HTTPException(401, "Open this from the Telegram bot.")
    if settings.allowed_users and user.get("id") not in settings.allowed_users:
        raise HTTPException(403, "Not allowed.")
    return user


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/forecast")
async def forecast(x_telegram_init_data: str | None = Header(default=None), refresh: bool = False):
    _check_user(x_telegram_init_data)
    async with _lock:  # one live refresh at a time; others reuse the cache
        try:
            return await asyncio.to_thread(get_forecast, refresh)
        except Exception as exc:
            raise HTTPException(502, f"Data source error: {exc}") from exc


@app.get("/")
async def root():
    return RedirectResponse("/app/")


# The Mini App page lives at the repo root (index.html). Serve only that one file,
# never the whole root folder, so source code and .env are not exposed.
@app.get("/app")
@app.get("/app/")
async def mini_app():
    return FileResponse(INDEX_HTML)
