"""Failures must explain themselves in the GitHub run summary (::error:: annotations).

Workflow logs of a public repo are public, so the messages must never contain secrets.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("RUNNER_TEMP", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import deliver  # noqa: E402
import telegram_sync as ts  # noqa: E402

SECRET = "super-secret-passphrase-value"


def run(main, argv, env):
    out = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
        code = main()
    return code, out.getvalue()


class ErrorAnnotationTests(unittest.TestCase):
    def test_missing_passphrase_is_explained(self):
        env = {"VAULT_PASSPHRASE": "", "TELEGRAM_TOKEN": "x"}
        code, out = run(ts.main, ["telegram_sync.py"], env)
        self.assertEqual(code, 1)
        self.assertIn("::error title=Gold Cambodia::VAULT_PASSPHRASE must be set", out)

    def test_missing_token_is_explained(self):
        with tempfile.TemporaryDirectory() as d:
            vault_path = Path(d) / "private.enc"
            with mock.patch.object(ts.vlt, "VAULT_PATH", vault_path):
                env = {"VAULT_PASSPHRASE": SECRET, "TELEGRAM_TOKEN": ""}
                code, out = run(ts.main, ["telegram_sync.py"], env)
        self.assertEqual(code, 1)
        self.assertIn("TELEGRAM_TOKEN is not set", out)
        self.assertIn("::error title=Gold Cambodia::", out)
        self.assertNotIn(SECRET, out)

    def test_deliver_reports_bad_passphrase(self):
        code, out = run(deliver.main, ["deliver.py"], {"VAULT_PASSPHRASE": "short"})
        self.assertEqual(code, 1)
        self.assertIn("::error title=Gold Cambodia::", out)


if __name__ == "__main__":
    unittest.main()
