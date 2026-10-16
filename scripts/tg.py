"""Tiny Telegram Bot API helper (standard library only) with a local outbox.

Messages are queued in an outbox file during a run and only sent by flush_outbox() AFTER the
vault change has been committed and pushed, so a failed push never produces duplicate or
phantom messages. The outbox lives in the runner's temp dir and is never committed.
"""
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

APP_URL = os.environ.get("APP_URL", "https://mechvannak.github.io/gold_market_cambodia/")
OUTBOX = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "gold_outbox.json"
MAX_LEN = 4000  # Telegram limit is 4096


class TgError(Exception):
    pass


def call(method: str, params: dict | None = None, timeout: int = 30) -> dict:
    token = os.environ.get("TELEGRAM_TOKEN", "")
    if not token:
        raise TgError("TELEGRAM_TOKEN is not set")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:  # never include the URL: it contains the bot token
        try:
            desc = json.loads(exc.read().decode()).get("description", "")
        except Exception:
            desc = ""
        raise TgError(f"{method}: HTTP {exc.code} {desc}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise TgError(f"{method}: {type(exc).__name__}") from None
    if not body.get("ok"):
        raise TgError(f"{method}: {body.get('description', 'error')}")
    return body["result"]


def get_updates(offset: int) -> list[dict]:
    return call("getUpdates", {"offset": offset, "timeout": 0, "limit": 100, "allowed_updates": ["message"]})


def keyboard() -> dict:
    """Reply keyboard with the mini app button; only apps opened from it can send forms (sendData)."""
    return {
        "keyboard": [[{"text": "📊 Gold Cambodia", "web_app": {"url": APP_URL}}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def split_text(text: str, limit: int = MAX_LEN) -> list[str]:
    parts, cur = [], ""
    for para in text.split("\n"):
        while len(para) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(para[:limit])
            para = para[limit:]
        if len(cur) + len(para) + 1 > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def queue_message(chat_id: int, text: str, with_keyboard: bool = False) -> None:
    box = json.loads(OUTBOX.read_text()) if OUTBOX.exists() else []
    box.append({"chat_id": chat_id, "text": text, "kb": with_keyboard})
    OUTBOX.write_text(json.dumps(box))


def flush_outbox() -> tuple[int, int]:
    """Send everything queued. Returns (sent, failed)."""
    if not OUTBOX.exists():
        return 0, 0
    box = json.loads(OUTBOX.read_text())
    sent = failed = 0
    for m in box:
        chunks = split_text(m["text"])
        try:
            for i, chunk in enumerate(chunks):
                params = {"chat_id": m["chat_id"], "text": chunk, "disable_web_page_preview": True}
                if m.get("kb") and i == len(chunks) - 1:
                    params["reply_markup"] = keyboard()
                call("sendMessage", params)
            sent += 1
        except TgError as exc:
            failed += 1
            print(f"send failed: {exc}")
    OUTBOX.unlink(missing_ok=True)
    return sent, failed
