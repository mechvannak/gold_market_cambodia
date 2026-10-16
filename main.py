"""Run the API/Mini App server and the Telegram bot in one process."""
import asyncio
import logging

import uvicorn

from app.api import app
from app.bot import run_bot
from app.config import settings


async def main():
    logging.basicConfig(level=logging.INFO)
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=settings.port, log_level="info"))
    jobs = [server.serve()]
    if settings.bot_token:
        jobs.append(run_bot())
    else:
        logging.warning("TELEGRAM_BOT_TOKEN not set: serving the web API only")
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
