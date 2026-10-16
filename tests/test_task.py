"""Tests for task_context.py, check_analysis.py and the example in CLAUDE_TASK.md.

Run with:  python -m unittest discover -s tests -v
"""
import copy
import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_analysis as ca  # noqa: E402
import task_context as tc  # noqa: E402

PP = timezone(timedelta(hours=7))


def at(y, m, d, h=7, mi=55):
    return datetime(y, m, d, h, mi, tzinfo=PP)


def market(price=4000.0, ma200=4000.0, high=4000.0, date="2026-10-19"):
    return {"date": date, "price_oz": price, "ma200": ma200, "high3m": high}


def task_example() -> dict:
    text = (ROOT / "CLAUDE_TASK.md").read_text(encoding="utf-8")
    block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
    return json.loads(block)


class ModeTests(unittest.TestCase):
    def test_monday_morning_is_weekly(self):
        self.assertEqual(tc.pick_mode(at(2026, 10, 19)), "weekly")  # Monday, not the first weekday

    def test_first_weekday_of_month_is_monthly(self):
        self.assertEqual(tc.pick_mode(at(2026, 10, 1)), "monthly")  # Thursday
        self.assertEqual(tc.pick_mode(at(2026, 5, 1)), "monthly")  # Friday

    def test_first_weekday_skips_weekend(self):
        # 1 Aug 2026 is a Saturday, so the first weekday is Monday 3 Aug; monthly wins over weekly
        self.assertEqual(tc.first_weekday_of_month(at(2026, 8, 20)).isoformat(), "2026-08-03")
        self.assertEqual(tc.pick_mode(at(2026, 8, 3)), "monthly")
        self.assertEqual(tc.pick_mode(at(2026, 8, 10)), "weekly")

    def test_evening_is_always_watchdog(self):
        self.assertEqual(tc.pick_mode(at(2026, 10, 19, 20, 55)), "watchdog")  # Monday evening
        self.assertEqual(tc.pick_mode(at(2026, 10, 1, 20, 55)), "watchdog")  # first weekday evening

    def test_midweek_morning_is_watchdog(self):
        self.assertEqual(tc.pick_mode(at(2026, 10, 21)), "watchdog")


class ContextTests(unittest.TestCase):
    def test_missing_market_blocks(self):
        c = tc.context(at(2026, 10, 19), None, None)
        self.assertFalse(c["market_ok"])
        self.assertIn("problem", c)

    def test_old_market_blocks(self):
        c = tc.context(at(2026, 10, 19), market(date="2026-10-10"), None)
        self.assertFalse(c["market_ok"])

    def test_friday_data_is_ok_on_monday(self):
        c = tc.context(at(2026, 10, 19), market(date="2026-10-16"), None)
        self.assertTrue(c["market_ok"])

    def test_decision_change_and_big_move(self):
        prev = {"market_decision": "HOLD", "price_at": 4000.0}
        c = tc.context(at(2026, 10, 21), market(price=3800.0, ma200=4000.0, high=4100.0, date="2026-10-21"), prev)
        self.assertEqual(c["market_decision"], "BUY_STEPS")
        self.assertTrue(c["decision_changed"])
        self.assertTrue(c["big_price_move"])
        self.assertTrue(c["watchdog_should_notify_without_news"])

    def test_quiet_market_stays_silent(self):
        prev = {"market_decision": "HOLD", "price_at": 4000.0}
        c = tc.context(at(2026, 10, 21), market(price=4040.0, date="2026-10-21"), prev)
        self.assertFalse(c["decision_changed"])
        self.assertFalse(c["big_price_move"])
        self.assertFalse(c["watchdog_should_notify_without_news"])

    def test_first_run_without_previous_analysis(self):
        c = tc.context(at(2026, 10, 21), market(date="2026-10-21"), None)
        self.assertFalse(c["decision_changed"])
        self.assertIsNone(c["price_move_pct_since_previous"])


class CheckAnalysisTests(unittest.TestCase):
    NOW = datetime(2026, 10, 19, 8, 0, tzinfo=PP)

    def good(self):
        a = task_example()
        a["generated_at"] = (self.NOW - timedelta(minutes=2)).isoformat(timespec="seconds")
        return a

    def test_example_in_task_file_is_valid(self):
        self.assertEqual(ca.validate(self.good(), self.NOW), [])

    def test_missing_timezone_is_rejected(self):
        a = self.good()
        a["generated_at"] = "2026-10-19T07:58:00"
        self.assertTrue(any("timezone" in p for p in ca.validate(a, self.NOW)))

    def test_stale_timestamp_is_rejected(self):
        a = self.good()
        a["generated_at"] = (self.NOW - timedelta(days=1)).isoformat()
        self.assertTrue(any("3 hours" in p for p in ca.validate(a, self.NOW)))
        self.assertEqual(ca.validate(a, self.NOW, check_age=False), [])

    def test_weekly_must_notify(self):
        a = self.good()
        a["notify"] = False
        self.assertTrue(any("notify true" in p for p in ca.validate(a, self.NOW)))

    def test_silent_watchdog_is_valid(self):
        a = self.good()
        a.update(mode="watchdog", notify=False)
        self.assertEqual(ca.validate(a, self.NOW), [])

    def test_bad_values_are_listed(self):
        a = self.good()
        a.update(confidence="certain", soften="no", market_decision="PANIC", price_at=-1)
        a["reasons_km"] = a["reasons_km"][:1]
        a["summary_en"] = "x" * 400
        a["sources"] = [{"title": "t", "url": "http://insecure.example"}]
        text = " ".join(ca.validate(a, self.NOW))
        for needle in ("confidence", "soften", "market_decision", "price_at", "same number", "summary_en", "sources[0]"):
            self.assertIn(needle, text)

    def test_not_an_object(self):
        self.assertEqual(ca.validate([], self.NOW), ["analysis must be a JSON object"])

    def test_compose_accepts_the_example(self):
        """The report builder must treat the documented example as fresh."""
        import compose

        info = compose.analysis_info(self.good(), self.NOW)
        self.assertTrue(info["fresh"])
        self.assertEqual(info["confidence"], "medium")
        self.assertEqual(len(info["reasons_km"]), 2)

    def test_copy_is_independent(self):
        a = self.good()
        b = copy.deepcopy(a)
        b["mode"] = "bogus"
        self.assertEqual(ca.validate(a, self.NOW), [])
        self.assertTrue(ca.validate(b, self.NOW))


if __name__ == "__main__":
    unittest.main()
