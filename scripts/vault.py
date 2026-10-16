"""Encrypted private vault: AES-256-GCM with a PBKDF2-HMAC-SHA256 key from VAULT_PASSPHRASE.

File format (JSON text in data/private.enc). The mini app reads the same format with WebCrypto:
  {"v":1, "kdf":"PBKDF2-SHA256", "iter":600000, "salt":b64, "iv":b64, "ct":b64}
ct = AES-256-GCM ciphertext followed by the 16-byte tag (what WebCrypto expects too).

Nothing here ever prints vault contents or the passphrase.
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

VAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "private.enc"
ITERATIONS = 600_000
MIN_PASSPHRASE = 12


class VaultError(Exception):
    pass


def default_vault() -> dict:
    return {
        "owner_chat_id": None,
        "last_update_id": 0,
        "last_analysis_at": "",
        "settings": {
            "lang": "both",
            "monthly_chi": 1.0,
            "hour": 9,
            "notify": {"weekly": True, "monthly": True, "watchdog": True},
        },
        "shop": {"sell": None, "buyback": None, "date": None},
        "purchases": [],
        "alerts": [],
        "queue": [],
        "reports": [],
    }


def _merge_defaults(data: dict, defaults: dict) -> dict:
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
        elif isinstance(v, dict) and isinstance(data[k], dict):
            _merge_defaults(data[k], v)
    return data


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(passphrase.encode("utf-8"))


def check_passphrase(passphrase: str | None) -> str:
    if not passphrase or len(passphrase) < MIN_PASSPHRASE:
        raise VaultError(f"VAULT_PASSPHRASE must be set and at least {MIN_PASSPHRASE} characters long")
    return passphrase


def encrypt(data: dict, passphrase: str, iterations: int = ITERATIONS) -> str:
    check_passphrase(passphrase)
    salt, iv = os.urandom(16), os.urandom(12)
    plain = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(_key(passphrase, salt, iterations)).encrypt(iv, plain, None)
    return json.dumps(
        {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": _b64(salt), "iv": _b64(iv), "ct": _b64(ct)}
    )


def decrypt(text: str, passphrase: str) -> dict:
    try:
        box = json.loads(text)
        salt, iv, ct = (base64.b64decode(box[k]) for k in ("salt", "iv", "ct"))
        key = _key(passphrase, salt, int(box["iter"]))
        return json.loads(AESGCM(key).decrypt(iv, ct, None).decode("utf-8"))
    except InvalidTag as exc:
        raise VaultError("Could not decrypt the vault (wrong passphrase or damaged file)") from exc
    except (KeyError, ValueError) as exc:
        raise VaultError("Vault file is not in the expected format") from exc


def load(passphrase: str | None = None, path: Path = VAULT_PATH) -> dict:
    """Return the vault. A missing file gives a fresh empty vault; a wrong passphrase raises."""
    passphrase = check_passphrase(passphrase or os.environ.get("VAULT_PASSPHRASE"))
    if not path.exists():
        return default_vault()
    return _merge_defaults(decrypt(path.read_text(), passphrase), default_vault())


def save(vault: dict, passphrase: str | None = None, path: Path = VAULT_PATH) -> None:
    passphrase = check_passphrase(passphrase or os.environ.get("VAULT_PASSPHRASE"))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = encrypt(vault, passphrase)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        try:
            v = load()
            print(f"vault ok: {len(v['purchases'])} purchases, owner {'set' if v['owner_chat_id'] else 'not set'}")
        except VaultError as exc:
            print(f"vault error: {exc}")
            sys.exit(1)
    else:
        print("usage: python scripts/vault.py check")
