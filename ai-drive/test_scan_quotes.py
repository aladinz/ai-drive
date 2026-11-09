import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "WebUI"))

import aladdin_stock_tools as stock_tools
import serve_webui
from trading_checklist import qualify_ticker


class ScanQuoteTests(unittest.TestCase):
    def test_toronto_symbol_is_accepted_without_changing_us_symbol(self):
        self.assertEqual(serve_webui.parse_input("GFL, GFL.TO, BRK.B"), ["GFL", "GFL.TO", "BRK.B"])

    def test_qualification_uses_regular_quote_and_unadjusted_history(self):
        history = pd.DataFrame({
            "Close": [60.0] * 30, "High": [61.0] * 30,
            "Low": [59.0] * 30, "Volume": [1_000_000] * 30,
        })
        info = {
            "regularMarketPrice": 65.40, "currentPrice": 64.0, "currency": "CAD",
            "exchange": "TOR", "regularMarketTime": 1793998799,
            "marketState": "CLOSED", "marketCap": 10_000_000_000,
        }

        class FakeTicker:
            calendar = {}

            def __init__(self, symbol):
                self.symbol = symbol
                self.info = info

            def history(self, **kwargs):
                self_test.assertEqual(kwargs, {"period": "1y", "auto_adjust": False})
                return history

        self_test = self
        stock_tools.quote_cache.clear()
        with patch("yfinance.Ticker", FakeTicker), patch.object(stock_tools.Tools, "_ma_20", return_value=60):
            data = stock_tools.Tools().qualification_data("GFL.TO")

        self.assertEqual(data["price"], 65.40)
        self.assertEqual(data["close"], 60.0)
        self.assertEqual(data["quote"], {
            "price": 65.40, "currency": "CAD", "exchange": "TOR",
            "timestamp": 1793998799, "market_state": "CLOSED",
        })
        result = qualify_ticker("GFL.TO", data)
        self.assertEqual(result["entry_price"], 65.40)
        self.assertAlmostEqual(result["target1_price"], 69.40)
        stock_tools.quote_cache.clear()

    def test_missing_or_nonfinite_quote_does_not_fall_back_to_history(self):
        class FakeTicker:
            info = {"regularMarketPrice": float("nan")}

            def __init__(self, symbol):
                pass

        stock_tools.quote_cache.clear()
        with patch("yfinance.Ticker", FakeTicker):
            self.assertIsNone(stock_tools.Tools().qualification_data("BAD"))


if __name__ == "__main__":
    unittest.main()
