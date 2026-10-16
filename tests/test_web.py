"""The mini app (index.html) must agree with the Python scripts.

  * decision rules and holdings maths in JavaScript == scripts/decide.py
  * the browser can decrypt what scripts/vault.py encrypts (including a Khmer passphrase)

Needs Node 18+ (for WebCrypto). Skipped when node is not installed.
Run with:  python -m unittest discover -s tests -v
"""
import json
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import decide  # noqa: E402
import vault  # noqa: E402

NODE = shutil.which("node")
CHECK = ROOT / "tests" / "web_core_check.js"


def run_node(request: dict):
    p = subprocess.run([NODE, str(CHECK)], input=json.dumps(request), capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


def random_case(rng: random.Random) -> dict:
    ma200 = rng.uniform(1500, 6000)
    price = ma200 * rng.uniform(0.80, 1.45)
    high = price * rng.uniform(1.0, 1.25)
    purchases = []
    chi_held = 0.0
    for i in range(rng.randint(0, 6)):
        if chi_held > 1 and rng.random() < 0.3:
            chi = round(rng.uniform(0.1, chi_held), 1)
            purchases.append({"id": i + 1, "type": "sell", "chi": chi, "price": round(rng.uniform(150, 700), 1), "date": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"})
            chi_held -= chi
        else:
            chi = round(rng.uniform(0.5, 5), 1)
            purchases.append({"id": i + 1, "type": "buy", "chi": chi, "price": round(rng.uniform(150, 700), 1), "date": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"})
            chi_held += chi
    return {
        "market": {"price_oz": round(price, 2), "ma200": round(ma200, 2), "high3m": round(high, 2)},
        "purchases": purchases,
        "ref_chi": rng.choice([None, round(rng.uniform(200, 900), 1)]),
        "monthly": rng.choice([0.5, 1, 1.5, 2, 3]),
    }


@unittest.skipUnless(NODE, "node is not installed")
class WebParityTests(unittest.TestCase):
    def test_decisions_match_python(self):
        rng = random.Random(2026)
        cases = [random_case(rng) for _ in range(400)]
        # exact threshold neighbours (floating-point behaviour must agree too)
        for factor in (1.15, 1.2, 1.25, 0.92, 1.0, 0.9999):
            cases.append({"market": {"price_oz": 4000 * factor, "ma200": 4000.0, "high3m": 4000 * factor / 0.92}, "purchases": [{"id": 1, "type": "buy", "chi": 5, "price": 250, "date": "2025-01-01"}], "ref_chi": 400, "monthly": 1})
        got = run_node({"op": "decide", "cases": cases})
        seen = set()
        for c, g in zip(cases, got):
            hold = decide.holdings(c["purchases"])
            ref = c["ref_chi"] if c["ref_chi"] is not None else decide.oz_to_chi(c["market"]["price_oz"])
            want = decide.decide(c["market"], hold, ref, c["monthly"])
            self.assertAlmostEqual(g["hold"]["chi"], hold["chi"], places=5)
            self.assertAlmostEqual(g["hold"]["avg_cost"], hold["avg_cost"], places=4)
            self.assertAlmostEqual(g["hold"]["realized"], hold["realized"], places=3)
            d = g["decision"]
            for key in ("rule", "action", "steps"):
                self.assertEqual(d[key], want[key], (key, c))
            for key in ("buy_chi", "sell_chi", "core_chi"):
                self.assertAlmostEqual(d[key], want[key], delta=0.011, msg=(key, c))
            seen.add(want["action"])
        self.assertEqual(seen, set(decide.ACTIONS), "test cases should exercise every action")

    def test_browser_decrypts_python_vault(self):
        data = vault.default_vault()
        data["purchases"] = [{"id": 1, "type": "buy", "chi": 2, "price": 400, "date": "2026-01-02"}]
        data["reports"] = [{"text_km": "របាយការណ៍ 🥇", "text_en": "report"}]
        for passphrase in ("correct horse battery staple", "ឃ្លាសម្ងាត់ វែង ណាស់ ៣២១"):
            text = vault.encrypt(data, passphrase, iterations=200_000)
            out = run_node({"op": "decrypt", "text": text, "pass": passphrase})
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["data"], data)

    def test_browser_rejects_wrong_passphrase_and_bad_files(self):
        text = vault.encrypt(vault.default_vault(), "correct horse battery staple", iterations=200_000)
        out = run_node({"op": "decrypt", "text": text, "pass": "wrong wrong wrong"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "OperationError")  # the app shows "wrong passphrase" for this
        box = json.loads(text)
        box["iter"] = 10  # a weak or hostile iteration count must be refused, not run
        out = run_node({"op": "decrypt", "text": json.dumps(box), "pass": "correct horse battery staple"})
        self.assertFalse(out["ok"])
        self.assertIn("unsupported", out["message"])


class IndexHtmlSafetyTests(unittest.TestCase):
    html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_no_secrets_or_tokens_in_the_page(self):
        for needle in ("TELEGRAM_TOKEN", "VAULT_PASSPHRASE", "api.telegram.org"):
            self.assertNotIn(needle, self.html)

    def test_passphrase_never_stored_in_browser_storage(self):
        self.assertNotIn("localStorage.setItem('gc_pass", self.html)
        self.assertEqual(self.html.count("localStorage.setItem"), 1)  # only the language choice

    def test_uses_kantumruy_pro_and_sea_sky_palette(self):
        self.assertIn("Kantumruy+Pro", self.html)
        self.assertIn("#0b5a86", self.html)  # sea blue
        self.assertIn("#5bbff2", self.html)  # sky blue


if __name__ == "__main__":
    unittest.main()
