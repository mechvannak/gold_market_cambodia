"""Run with:  python -m unittest discover -s tests -v   (needs: pip install cryptography)"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["RUNNER_TEMP"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import compose  # noqa: E402
import decide  # noqa: E402
import deliver  # noqa: E402
import market  # noqa: E402
import telegram_sync as ts  # noqa: E402
import tg  # noqa: E402
import vault  # noqa: E402

PP = timezone(timedelta(hours=7))
PASS = "correct horse battery staple"


def mkt(price=4000.0, ma200=4000.0, high=4000.0, **kw):
    m = {
        "price_oz": price, "ma200": ma200, "high3m": high, "usd_khr": 4050.0,
        "above_ma200_pct": round((price / ma200 - 1) * 100, 2),
        "from_high3m_pct": round((price / high - 1) * 100, 2),
    }
    m.update(kw)
    return m


def hold(chi=10.0, avg=300.0):
    return {"chi": chi, "avg_cost": avg}


class DecideTests(unittest.TestCase):
    def test_rule1_sell_in_steps_keeps_core(self):
        # 22% above 200d, world chi price well above cost -> profit >= 50%
        m = mkt(price=4880, ma200=4000, high=4900)
        ref = decide.oz_to_chi(m["price_oz"])
        d = decide.decide(m, hold(10, 300), ref)
        self.assertEqual((d["rule"], d["action"]), (1, "SELL_STEPS"))
        self.assertEqual(d["buy_chi"], 0)
        self.assertAlmostEqual(d["sell_chi"] * d["steps"], 7.0, places=1)  # 70% sellable, 30% core kept
        self.assertEqual(d["core_chi"], 3.0)

    def test_rule1_needs_profit(self):
        m = mkt(price=4880, ma200=4000, high=4900)  # +22%
        d = decide.decide(m, hold(10, 450), decide.oz_to_chi(4880))  # tiny profit
        self.assertEqual(d["action"], "WAIT")

    def test_rule2_reduce_never_enters_core(self):
        d = decide.decide(mkt(5100, 4000, 5100), hold(10, 600), decide.oz_to_chi(5100))
        self.assertEqual((d["rule"], d["action"]), (2, "REDUCE"))
        self.assertLessEqual(d["sell_chi"], 7.0)
        self.assertEqual(d["sell_chi"], 1.5)

    def test_rule3_wait_half_monthly(self):
        d = decide.decide(mkt(4700, 4000, 4700), hold(), None, monthly_chi=2)
        self.assertEqual((d["rule"], d["action"], d["buy_chi"]), (3, "WAIT", 1.0))

    def test_rule4_dip_and_below_ma(self):
        dip = decide.decide(mkt(4100, 4000, 4500), None, None, monthly_chi=1)  # 8.9% below high, above 200d
        self.assertEqual((dip["action"], dip["buy_chi"]), ("BUY_EXTRA", 1.5))
        below = decide.decide(mkt(3900, 4000, 4000), None, None, monthly_chi=1)
        self.assertEqual((below["action"], below["buy_chi"], below["steps"]), ("BUY_STEPS", 2.0, 3))

    def test_rule5_hold(self):
        d = decide.decide(mkt(4100, 4000, 4150), None, None, monthly_chi=1)
        self.assertEqual((d["rule"], d["action"], d["buy_chi"]), (5, "HOLD", 1.0))

    def test_market_decision_and_bad_data(self):
        self.assertEqual(decide.market_decision(mkt(3900, 4000, 4000)), "BUY_STEPS")
        with self.assertRaises(ValueError):
            decide.decide({"price_oz": 1})

    def test_holdings_average_cost_and_realized(self):
        p = [
            {"id": 1, "type": "buy", "chi": 2, "price": 400, "date": "2026-01-01"},
            {"id": 2, "type": "buy", "chi": 2, "price": 500, "date": "2026-02-01"},
            {"id": 3, "type": "sell", "chi": 1, "price": 550, "date": "2026-03-01"},
        ]
        h = decide.holdings(p)
        self.assertAlmostEqual(h["chi"], 3)
        self.assertAlmostEqual(h["avg_cost"], 450)
        self.assertAlmostEqual(h["realized"], 100)

    def test_chi_conversion(self):
        self.assertAlmostEqual(decide.CHI_PER_OZ, 8.2942, places=3)


class VaultTests(unittest.TestCase):
    def test_round_trip_and_wrong_passphrase(self):
        data = {"a": 1, "k": "ខ្មែរ"}
        text = vault.encrypt(data, PASS, iterations=1000)
        self.assertEqual(vault.decrypt(text, PASS), data)
        with self.assertRaises(vault.VaultError):
            vault.decrypt(text, "wrong passphrase value")
        self.assertNotIn("ខ្មែរ", text)

    def test_short_passphrase_refused(self):
        with self.assertRaises(vault.VaultError):
            vault.encrypt({}, "short")

    def test_save_load_and_defaults(self):
        p = Path(tempfile.mkdtemp()) / "private.enc"
        self.assertEqual(vault.load(PASS, p)["settings"]["hour"], 9)  # missing file -> fresh vault
        v = vault.default_vault()
        v["purchases"].append({"id": 1})
        vault.save(v, PASS, p)
        self.assertEqual(vault.load(PASS, p)["purchases"], [{"id": 1}])
        with self.assertRaises(vault.VaultError):
            vault.load("another passphrase here", p)


def fake_chart(n=300, last=4000.0):
    start = datetime(2025, 6, 1, tzinfo=timezone.utc)
    ts = [int((start + timedelta(days=i)).timestamp()) for i in range(n)]
    close = [3000 + i * (last - 3000) / (n - 1) for i in range(n)]
    quote = {"open": close, "high": [c + 5 for c in close], "low": [c - 5 for c in close], "close": close}
    quote["close"][10] = None  # gaps must be skipped
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [quote]}, "meta": {"regularMarketPrice": last}}]}}


class MarketTests(unittest.TestCase):
    def test_build_market(self):
        rows, last = market.parse_chart(fake_chart())
        self.assertEqual(len(rows), 299)
        now = datetime(2026, 3, 27, 7, 15, tzinfo=PP)
        m, out = market.build_market(rows, last, 4020.0, "test", None, now)
        self.assertEqual(m["price_oz"], 4000.0)
        self.assertTrue(m["ma200"] < m["ma50"] < m["ma20"] <= m["high3m"])
        self.assertAlmostEqual(m["price_chi"], 4000 / decide.CHI_PER_OZ, places=2)
        self.assertGreater(m["above_ma200_pct"], 0)
        self.assertEqual(m["usd_khr"], 4020.0)

    def test_khr_fallback_uses_previous(self):
        rows, last = market.parse_chart(fake_chart())
        m, _ = market.build_market(rows, last, None, "", {"usd_khr": 4011.0, "khr_source": "x"}, datetime(2026, 3, 27, tzinfo=PP))
        self.assertEqual(m["usd_khr"], 4011.0)

    def test_rejects_short_history_and_insane_price(self):
        rows, last = market.parse_chart(fake_chart(n=100))
        with self.assertRaises(RuntimeError):
            market.build_market(rows, last, 4000.0, "t", None, datetime(2026, 3, 27, tzinfo=PP))
        rows, _ = market.parse_chart(fake_chart())
        with self.assertRaises(RuntimeError):
            market.build_market(rows, 5.0, 4000.0, "t", None, datetime(2026, 3, 27, tzinfo=PP))


def vault_with_owner():
    v = vault.default_vault()
    v["owner_chat_id"] = 111
    return v


class CommandTests(unittest.TestCase):
    TODAY = "2026-10-16"

    def run_cmd(self, v, line, market_=None):
        return ts.apply_command(v, line, self.TODAY, market_)

    def test_buy_sell_flow(self):
        v = vault_with_owner()
        self.assertIn("✅", self.run_cmd(v, "/buy 2 400"))
        self.assertIn("✅", self.run_cmd(v, "/buy 2 500 2026-10-01"))
        r = self.run_cmd(v, "/sell 1 550")
        self.assertIn("✅", r)
        h = decide.holdings(v["purchases"])
        self.assertAlmostEqual(h["chi"], 3)
        self.assertIn("❌", self.run_cmd(v, "/sell 99 550"))
        self.assertIn("❌", self.run_cmd(v, "/buy abc 400"))
        self.assertIn("❌", self.run_cmd(v, "/buy 1 400 2999-01-01"))

    def test_unit_mistake_warning(self):
        v = vault_with_owner()
        r = self.run_cmd(v, "/buy 1 4000", {"price_oz": 4000})
        self.assertIn("$/oz", r)

    def test_settings_commands(self):
        v = vault_with_owner()
        self.run_cmd(v, "/shop 510 503")
        self.assertEqual((v["shop"]["sell"], v["shop"]["buyback"]), (510, 503))
        self.assertIn("❌", self.run_cmd(v, "/shop 500 510"))  # buyback above sell
        self.run_cmd(v, "/monthly 1.5")
        self.assertEqual(v["settings"]["monthly_chi"], 1.5)
        self.run_cmd(v, "/lang km")
        self.assertEqual(v["settings"]["lang"], "km")
        self.run_cmd(v, "/lang en")
        self.run_cmd(v, "/time 10")
        self.assertEqual(v["settings"]["hour"], 10)
        self.assertIn("❌", self.run_cmd(v, "/time 7"))
        self.assertIn("❌", self.run_cmd(v, "/time 21"))
        self.run_cmd(v, "/notify weekly off")
        self.assertFalse(v["settings"]["notify"]["weekly"])
        self.assertIn("❌", self.run_cmd(v, "/notify daily on"))

    def test_alerts(self):
        v = vault_with_owner()
        self.run_cmd(v, "/alert below 4000")
        self.run_cmd(v, "/alert above 500 chi")
        self.assertEqual([(a["dir"], a["unit"]) for a in v["alerts"]], [("below", "oz"), ("above", "chi")])
        self.assertIn("below", self.run_cmd(v, "/alerts"))
        self.run_cmd(v, "/alert clear")
        self.assertEqual(v["alerts"], [])
        self.assertIn("❌", self.run_cmd(v, "/alert sideways 5"))

    def test_language_both_has_khmer_and_english(self):
        v = vault_with_owner()
        r = self.run_cmd(v, "/monthly 2")
        self.assertIn("Monthly buy", r)
        self.assertRegex(r, "[ក-៿]")

    def test_owner_binding_and_ignoring_strangers(self):
        tg.OUTBOX.unlink(missing_ok=True)
        v = vault.default_vault()
        msg = lambda uid, cid, text, **kw: {"update_id": uid, "message": {"chat": {"id": cid, "type": "private"}, "text": text, **kw}}
        ts.process_updates(v, [msg(1, 999, "/buy 1 400")], self.TODAY, None)  # before /start: ignored
        self.assertIsNone(v["owner_chat_id"])
        ts.process_updates(v, [msg(2, 111, "/start"), msg(3, 222, "/start"), msg(4, 222, "/buy 5 400")], self.TODAY, None)
        self.assertEqual(v["owner_chat_id"], 111)
        self.assertEqual(v["purchases"], [])
        self.assertEqual(v["last_update_id"], 4)
        sent = json.loads(tg.OUTBOX.read_text())
        self.assertEqual([m["chat_id"] for m in sent], [111])
        self.assertTrue(sent[0]["kb"])

    def test_mini_app_form_runs_several_commands(self):
        v = vault_with_owner()
        form = "/time 11\n/notify watchdog off\n/lang km\nnot a command\n/buy 1 400"
        upd = {"update_id": 9, "message": {"chat": {"id": 111, "type": "private"}, "web_app_data": {"data": form, "button_text": "x"}}}
        ts.process_updates(v, [upd], self.TODAY, None)
        self.assertEqual(v["settings"]["hour"], 11)
        self.assertFalse(v["settings"]["notify"]["watchdog"])
        self.assertEqual(v["settings"]["lang"], "km")
        self.assertEqual(len(v["purchases"]), 1)

    def test_group_chats_ignored(self):
        v = vault.default_vault()
        u = {"update_id": 1, "message": {"chat": {"id": 5, "type": "group"}, "text": "/start"}}
        ts.process_updates(v, [u], self.TODAY, None)
        self.assertIsNone(v["owner_chat_id"])


class ComposeTests(unittest.TestCase):
    NOW = datetime(2026, 10, 19, 8, 0, tzinfo=PP)

    def analysis(self, **kw):
        a = {
            "generated_at": (self.NOW - timedelta(hours=1)).isoformat(), "mode": "weekly", "confidence": "high",
            "reasons_en": ["Dollar is weakening"], "reasons_km": ["ដុល្លារកំពុងធ្លាក់ថ្លៃ"],
        }
        a.update(kw)
        return a

    def vault_with_gold(self):
        v = vault_with_owner()
        v["purchases"] = [{"id": 1, "type": "buy", "chi": 4, "price": 400, "date": "2026-01-01"}]
        return v

    def test_report_is_bilingual_with_numbers(self):
        m = mkt(4200, 4000, 4300, above_ma200_pct=5.0, from_high3m_pct=-2.3)
        r = compose.build_report("weekly", m, self.analysis(), self.vault_with_gold(), self.NOW)
        self.assertEqual(r["action"], "HOLD")
        for key in ("text_en", "text_km"):
            self.assertIn("$4,200/", r[key])
        self.assertIn("/oz", r["text_en"])
        self.assertIn("/អោន", r["text_km"])
        self.assertIn("Dollar is weakening", r["text_en"])
        self.assertIn("ដុល្លារកំពុងធ្លាក់ថ្លៃ", r["text_km"])
        both = compose.render(r, "both")
        self.assertTrue(both.index("មាសកម្ពុជា") < both.index("Gold Cambodia"))
        self.assertLess(len(both), 4000 * 2)

    def test_soften_halves_plan_but_never_changes_action(self):
        m = mkt(3900, 4000, 4000, above_ma200_pct=-2.5, from_high3m_pct=-2.5)
        v = self.vault_with_gold()
        normal = compose.build_report("monthly", m, self.analysis(), v, self.NOW)
        soft = compose.build_report("monthly", m, self.analysis(soften=True), v, self.NOW)
        self.assertEqual(normal["action"], soft["action"], "BUY_STEPS")
        self.assertIn("Buy 2 chi", normal["text_en"])
        self.assertIn("Buy 1 chi", soft["text_en"])
        self.assertIn("softer plan", soft["text_en"])

    def test_stale_analysis_lowers_confidence_and_says_so(self):
        old = self.analysis(generated_at=(self.NOW - timedelta(days=9)).isoformat())
        r = compose.build_report("weekly", mkt(), old, self.vault_with_gold(), self.NOW)
        self.assertIn("No fresh Claude analysis", r["text_en"])
        self.assertNotIn("Dollar is weakening", r["text_en"])

    def test_profit_uses_shop_buyback_when_known(self):
        v = self.vault_with_gold()
        v["shop"] = {"sell": 510, "buyback": 480, "date": "2026-10-19"}
        r = compose.build_report("weekly", mkt(4200, 4000, 4300, above_ma200_pct=5, from_high3m_pct=-2), self.analysis(), v, self.NOW)
        self.assertIn("+20.0%", r["text_en"])
        self.assertIn("shop buyback", r["text_en"])

    def test_untrusted_analysis_text_is_cleaned(self):
        a = self.analysis(reasons_en=["ok\x00\x07" + "x" * 1000])
        r = compose.build_report("weekly", mkt(), a, vault_with_owner(), self.NOW)
        self.assertNotIn("\x00", r["text_en"])
        self.assertLess(len(r["text_en"]), 3000)


class DeliverTests(unittest.TestCase):
    def test_queue_waits_for_hour(self):
        v = vault_with_owner()
        v["settings"]["hour"] = 9
        v["queue"] = [{"id": 1, "kind": "weekly", "text_en": "e", "text_km": "k"}]
        tg.OUTBOX.unlink(missing_ok=True)
        self.assertEqual(deliver.deliver_queue(v, datetime(2026, 10, 19, 8, 5, tzinfo=PP)), 0)
        self.assertEqual(deliver.deliver_queue(v, datetime(2026, 10, 19, 9, 5, tzinfo=PP)), 1)
        self.assertEqual((v["queue"], len(v["reports"])), ([], 1))
        self.assertTrue(v["reports"][0]["delivered"])

    def test_alerts_fire_once(self):
        v = vault_with_owner()
        v["alerts"] = [
            {"dir": "below", "level": 4000, "unit": "oz", "fired": False},
            {"dir": "above", "level": 600, "unit": "chi", "fired": False},
            {"dir": "below", "level": 3000, "unit": "oz", "fired": False},
        ]
        tg.OUTBOX.unlink(missing_ok=True)
        now = datetime(2026, 10, 19, 9, tzinfo=PP)
        self.assertEqual(deliver.check_alerts(v, 3950.0, now), 1)  # only the first (3950 <= 4000)
        self.assertEqual(deliver.check_alerts(v, 3950.0, now), 0)  # already fired
        self.assertEqual(deliver.check_alerts(v, 5200.0, now), 1)  # 5200/oz = 627 chi >= 600


class TgTests(unittest.TestCase):
    def test_split_text(self):
        text = "\n".join(["line " * 20] * 100)
        parts = tg.split_text(text, 500)
        self.assertTrue(all(len(p) <= 500 for p in parts))
        self.assertEqual("\n".join(parts).replace("\n", ""), text.replace("\n", ""))

    def test_no_token_means_clear_error(self):
        os.environ.pop("TELEGRAM_TOKEN", None)
        with self.assertRaises(tg.TgError):
            tg.call("getMe")


if __name__ == "__main__":
    unittest.main()
