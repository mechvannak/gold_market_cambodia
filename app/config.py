import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; plain environment variables still work
    pass


def _ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit())


class Settings:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    anthropic_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    webapp_url: str = os.getenv("WEBAPP_URL", "").rstrip("/")
    port: int = int(os.getenv("PORT", "8080"))
    allowed_users: frozenset[int] = _ids(os.getenv("ALLOWED_USER_IDS", ""))
    dev_mode: bool = os.getenv("DEV_MODE", "0") == "1"
    cache_ttl: int = int(os.getenv("CACHE_TTL_SECONDS", "600"))
    alert_hour: int = int(os.getenv("ALERT_HOUR", "8"))
    timezone: str = os.getenv("TIMEZONE", "Asia/Bangkok")


settings = Settings()
