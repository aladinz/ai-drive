import unittest

from trading_checklist import (
    calculate_atr_levels,
    calculate_scaling_plan,
    check_rr,
    qualify_ticker,
)


class AtrLevelsTests(unittest.TestCase):
    def test_default_targets_use_three_atr_multiples(self):
        levels = calculate_atr_levels(42.08, 1.31)

        self.assertAlmostEqual(levels["stop_price"], 40.115)
        self.assertAlmostEqual(levels["tp1_price"], 44.70)
        self.assertAlmostEqual(levels["tp2_price"], 46.01)
        self.assertAlmostEqual(levels["tp3_price"], 47.975)
        self.assertLess(levels["stop_price"], levels["tp1_price"])
        self.assertLess(levels["tp1_price"], levels["tp2_price"])
        self.assertLess(levels["tp2_price"], levels["tp3_price"])

    def test_rr_check_uses_core_tp2(self):
        result = check_rr(42.08, None, None, 1.31)
        plan = calculate_scaling_plan(
            42.08, 1.31, total_shares=170, stop_price=result["stop_price"]
        )

        self.assertTrue(result["pass"])
        self.assertAlmostEqual(result["rr_t1"], 2 / 1.5)
        self.assertAlmostEqual(result["rr_t2"], 2.0)
        self.assertAlmostEqual(result["rr_t3"], 3.0)
        self.assertIn("TP1 2x TP2 3x TP3 4.5x R/R 2.00R", result["detail"])
        self.assertAlmostEqual(result["target1_price"], 44.70)
        self.assertAlmostEqual(result["target2_price"], 46.01)
        self.assertAlmostEqual(result["target3_price"], 47.975)
        self.assertAlmostEqual(plan["tp1"]["price"], result["target1_price"])
        self.assertAlmostEqual(plan["tp2"]["price"], result["target2_price"])
        self.assertAlmostEqual(plan["tp3"]["price"], result["target3_price"])

    def test_stop_guard_does_not_change_atr_target_prices(self):
        levels = calculate_atr_levels(100, 4)

        self.assertEqual(levels["stop_pct"], 5.0)
        self.assertAlmostEqual(levels["stop_price"], 95)
        self.assertAlmostEqual(levels["tp1_price"], 108)
        self.assertAlmostEqual(levels["tp2_price"], 112)
        self.assertAlmostEqual(levels["tp3_price"], 118)
        self.assertAlmostEqual(levels["tp2_rr"], 2.4)

    def test_qualified_setup_uses_the_same_atr_targets(self):
        result = qualify_ticker("TEST", {
            "price": 42.08,
            "close": 42.08,
            "sma50": 41,
            "sma200": 39,
            "avg_volume_20d": 1_000_000,
            "volume": 2_000_000,
            "atr": 1.31,
            "rsi": 55,
            "market_cap": 10_000_000_000,
            "lows": [39, 40, 41],
            "high": 43,
            "low": 41,
            "events": [],
        })

        self.assertTrue(result["qualified"])
        self.assertAlmostEqual(result["target1_price"], 44.70)
        self.assertAlmostEqual(result["target2_price"], 46.01)
        self.assertAlmostEqual(result["target3_price"], 47.975)
        self.assertAlmostEqual(result["rr_t2"], 2.0)


if __name__ == "__main__":
    unittest.main()
