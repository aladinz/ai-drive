"""
title: Aladdin Stock Tools
author: Aladdin
version: 1.0.0
description: Web search (DuckDuckGo) and Yahoo Finance quotes for Llama 3.1 8B Instruct.
requirements: duckduckgo-search, yfinance
"""

import json
import os
import sys
import threading
import time

from pydantic import BaseModel, Field

CHECKLIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai-drive")
if CHECKLIST_DIR not in sys.path:
    sys.path.insert(0, CHECKLIST_DIR)

QUOTE_CACHE_SECONDS = 10
quote_cache = {}  # symbol -> (monotonic timestamp, quote dict)
_cache_lock = threading.Lock()


class Tools:
    class Valves(BaseModel):
        MAX_RESULTS: int = Field(default=5, description="Number of web results to return")
        TIMEOUT: int = Field(default=10, description="Web search timeout in seconds")

    def __init__(self):
        self.valves = self.Valves()

    def pennant_pattern(
        self,
        high1: float,
        low1: float,
        high2: float,
        low2: float,
        high3: float,
        low3: float,
    ) -> str:
        """Check whether three chronological swing pivots form a narrowing pennant."""
        from trading_checklist import pennant_pattern

        return json.dumps(pennant_pattern(high1, low1, high2, low2, high3, low3))

    def web_search(self, query: str) -> str:
        """
        Search the web for real-time information, news, stock quotes, SEC filings.
        :param query: The search query string.
        :return: Top results with title, link and snippet.
        """
        try:
            from duckduckgo_search import DDGS

            with DDGS(timeout=self.valves.TIMEOUT) as ddgs:
                results = list(ddgs.text(query, max_results=self.valves.MAX_RESULTS))
            if not results:
                return f"No results found for: {query}"
            return "\n\n".join(
                f"{i}. {r.get('title', '')}\n   URL: {r.get('href', '')}\n   {r.get('body', '')}"
                for i, r in enumerate(results, 1)
            )
        except Exception as e:
            return f"Web search failed: {e}"

    def yahoo_finance(self, symbol: str, risk: float = 0.015, account: float = 0.0) -> str:
        """
        Get live stock price, volume, moving averages, 52-week high/low for a ticker symbol, plus a breakout trade setup (entry, stop, targets, risk/reward, volume check).
        :param symbol: Stock ticker symbol, e.g. "ATRC".
        :param risk: Account risk per trade as a fraction (0.015 = 1.5%). Also sets the stop buffer below the day's low (risk / 2).
        :param account: Account size in dollars (optional); when given, position size is calculated.
        :return: JSON string with price, market data and a "setup" plan.
        """
        symbol = (symbol or "").strip().upper()
        if not symbol:
            return json.dumps({"error": "No ticker symbol provided"})
        try:
            data = self._get_quote(symbol)
            if data is None:
                return json.dumps({"error": f"Invalid or unknown symbol: {symbol}"})
            setup = self._trigger_plan(data, risk, account)
            return json.dumps(
                {
                    "symbol": symbol,
                    "instruction": "Report the setup summary, entry, stop, targets and R:R to the user with exact numbers.",
                    "setup": setup,
                    **{k: v for k, v in data.items() if k != "symbol"},
                }
            )
        except Exception as e:
            return json.dumps({"error": f"Lookup failed for {symbol}: {e}"})

    def _get_quote(self, symbol: str):
        """Internal: quote dict from Yahoo, cached per symbol for QUOTE_CACHE_SECONDS."""
        now = time.monotonic()
        with _cache_lock:
            hit = quote_cache.get(symbol)
            if hit and now - hit[0] < QUOTE_CACHE_SECONDS:
                return hit[1]
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            return None
        data = {
            "symbol": symbol,
            "name": info.get("shortName") or info.get("longName") or symbol,
            "ma_20": self._ma_20(yf, symbol),
            "currentPrice": price,
            "previousClose": info.get("previousClose"),
            "open": info.get("open") or info.get("regularMarketOpen"),
            "dayHigh": info.get("dayHigh"),
            "dayLow": info.get("dayLow"),
            "volume": info.get("volume"),
            "averageVolume": info.get("averageVolume"),
            "fiftyDayAverage": info.get("fiftyDayAverage"),
            "twoHundredDayAverage": info.get("twoHundredDayAverage"),
            "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
            "marketCap": info.get("marketCap"),
        }
        with _cache_lock:
            quote_cache[symbol] = (now, data)
        return data

    def qualification_data(self, symbol: str):
        """Internal: market_data dict for trading_checklist.qualify_ticker, or None if lookup fails."""
        symbol = (symbol or "").strip().upper()
        quote = self._get_quote(symbol) if symbol else None
        if not quote:
            return None
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y").dropna(subset=["Close", "High", "Low", "Volume"])
        if len(hist) < 30:
            return None
        close, high, low, vol = hist["Close"], hist["High"], hist["Low"], hist["Volume"]
        prev_close = close.shift(1)
        true_range = (
            (high - low).to_frame("a").join((high - prev_close).abs().rename("b")).join((low - prev_close).abs().rename("c")).max(axis=1)
        )
        atr = float(true_range.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        last_loss = float(loss.iloc[-1])
        rsi = 100.0 if last_loss == 0 else 100 - 100 / (1 + float(gain.iloc[-1]) / last_loss)

        price = float(close.iloc[-1])
        window_high = float(high.tail(120).max())
        year_high = float(high.max())
        info = {}
        try:
            info = ticker.info or {}
        except Exception:
            pass
        events = []
        try:
            calendar = ticker.calendar or {}
            for when in calendar.get("Earnings Date") or []:
                events.append({"type": "earnings", "date": str(when)[:10]})
        except Exception:
            pass

        return {
            "price": price,
            "sma50": float(close.tail(50).mean()) if len(close) >= 50 else None,
            "sma200": float(close.tail(200).mean()) if len(close) >= 200 else None,
            "avg_volume_20d": float(vol.tail(20).mean()),
            "volume": float(vol.iloc[-1]),
            "atr": atr,
            "rsi": rsi,
            "market_cap": quote.get("marketCap"),
            "bid": info.get("bid"),
            "ask": info.get("ask"),
            "lows": [float(x) for x in low.tail(3)],
            "high": float(high.iloc[-1]),
            "low": float(low.iloc[-1]),
            "close": price,
            "target1": window_high if window_high > price else None,
            "target2": year_high if year_high > price and year_high != window_high else None,
            # Tight stop: the higher of the 5-day low and 1.5x ATR below price.
            "stop": max(float(low.tail(5).min()), price - 1.5 * atr),
            "events": events,
        }

    @staticmethod
    def _ma_20(yf, symbol: str):
        """Internal: 20-day simple moving average of closes, or None if unavailable."""
        try:
            closes = yf.Ticker(symbol).history(period="2mo")["Close"].dropna()
            return round(float(closes.tail(20).mean()), 4) if len(closes) >= 20 else None
        except Exception:
            return None

    def _trigger_plan(self, d: dict, risk: float = 0.015, account: float = 0.0) -> dict:
        """Internal: breakout plan computed from a yahoo_finance quote (not an LLM tool)."""
        need = ("currentPrice", "dayHigh", "dayLow", "fiftyTwoWeekHigh")
        if any(not d.get(k) for k in need):
            return {"status": "NO_DATA", "reason": "Missing price/high/low/52-week data"}
        return self._calculate(
            current_price=d["currentPrice"],
            high_today=d["dayHigh"],
            low_today=d["dayLow"],
            volume=d.get("volume") or 0,
            avg_volume=d.get("averageVolume") or 0,
            week_52_high=d["fiftyTwoWeekHigh"],
            week_52_low=d.get("fiftyTwoWeekLow") or 0,
            ma_20=d.get("ma_20") or 0,
            ma_50=d.get("fiftyDayAverage") or 0,
            risk=risk,
            account=account,
        )

    def _calculate(
        self,
        current_price: float,
        high_today: float,
        low_today: float,
        volume: int,
        avg_volume: int,
        week_52_high: float,
        week_52_low: float = 0.0,
        ma_20: float = 0.0,
        ma_50: float = 0.0,
        atr: float = 0.0,
        risk: float = 0.015,
        account: float = 0.0,
    ) -> dict:
        """Internal: breakout entry, stop, two targets and risk/reward."""
        try:
            risk_pct = float(risk) if risk else 0.015
            if risk_pct >= 1:  # model passed a percent such as 2 instead of 0.02
                risk_pct /= 100
            if not 0 < risk_pct <= 0.2:
                risk_pct = 0.015
            account = float(account or 0)
        except (TypeError, ValueError):
            risk_pct, account = 0.015, 0.0
        stop_buffer = risk_pct * 0.5
        try:
            price, high, low = float(current_price), float(high_today), float(low_today)
            vol, avg_vol = float(volume), float(avg_volume)
            wk_high, wk_low = float(week_52_high), float(week_52_low or 0)
            ma = float(ma_20 or 0) or float(ma_50 or 0)
            atr_val = float(atr or 0) or (high - low)
        except (TypeError, ValueError) as e:
            return {"status": "NO_DATA", "reason": f"Invalid numeric input: {e}"}
        if min(price, high, low, wk_high) <= 0 or high < low:
            return {"status": "NO_DATA", "reason": "Prices must be positive and high >= low"}

        entry = high + 0.10
        stop = max(low * (1 - stop_buffer), price - 1.5 * atr_val)
        risk = entry - stop
        ma20_v, ma50_v = float(ma_20 or 0), float(ma_50 or 0)
        pct_range = (price - wk_low) / (wk_high - wk_low) * 100 if wk_high > wk_low else 50.0
        measured = entry + 2.5 * risk
        near_high_t2 = min(
            [t for t in (wk_high * 1.08, measured) if t > wk_high] or [wk_high * 1.08]
        )

        if pct_range >= 80 or wk_high <= entry:
            zone = "near_high"
            target_1, target_2 = max(wk_high, entry + risk), near_high_t2
            t1_reason = "52-week high retest"
            t2_reason = "Lower of 8% above 52W high and 2.5R measured breakout"
        elif pct_range >= 50:
            zone = "mid_range"
            target_1, target_2 = measured, wk_high
            t1_reason = "2.5R measured move (first resistance)"
            t2_reason = "52-week high"
            if target_1 >= target_2:  # 52W high is closer than 2.5R
                target_1, target_2 = wk_high, wk_high * 1.08
                t1_reason, t2_reason = "52-week high retest", "8% above 52W high"
        else:
            zone = "near_low"
            retrace = entry + 0.5 * (wk_high - entry)
            target_1 = ma20_v if ma20_v > entry else entry * 1.10
            t1_reason = "20-day MA" if ma20_v > entry else "10% above entry"
            if ma50_v > target_1:
                target_2, t2_reason = ma50_v, "50-day MA"
            else:
                target_2, t2_reason = max(retrace, target_1 * 1.05), "50% retracement to 52W high"
        reward_1, reward_2 = target_1 - entry, target_2 - entry
        r1, r2 = reward_1 / risk, reward_2 / risk
        required_vol = avg_vol * 0.8
        volume_ok = avg_vol <= 0 or vol >= required_vol
        rr_ok = round(r1, 1) >= 1.0 and round(r2, 1) >= 2.0

        trigger = f"close above ${high:.2f}"
        if not rr_ok:
            status = "NO_SETUP"
            summary = f"Risk/reward too low (R1 {r1:.2f}, R2 {r2:.2f}); need R1>=1.0 and R2>=2.0."
        elif not volume_ok:
            status = "WATCHLIST"
            summary = (
                f"Setup WATCHLIST: volume light today {vol / 1000:,.0f}K "
                f"(needs {required_vol / 1000:,.0f}K). Entry valid ONLY on a volume surge "
                f"above {required_vol / 1000:,.0f}K with a {trigger}. "
                f"R:R {r1:.2f} ~ 1:1 passes."
            )
        else:
            status = "VALID"
            summary = f"Setup VALID: {trigger} at ${entry:.2f}; volume confirmed."

        result = {
            "status": status,
            "summary": summary,
            "required_volume": int(required_vol),
            "entry_trigger": round(entry, 2),
            "entry_condition": f"{trigger.capitalize()} on volume >{int(required_vol):,}",
            "stop": round(stop, 2),
            "stop_reason": f"Tight stop: higher of {stop_buffer * 100:.2f}% below today's low and 1.5x ATR below price",
            "target_1": round(target_1, 2),
            "target_1_reason": t1_reason,
            "target_1_gain_pct": round(reward_1 / entry * 100, 1),
            "target_2": round(target_2, 2),
            "target_2_reason": t2_reason,
            "range_zone": zone,
            "range_pct": round(pct_range, 1),
            "target_2_gain_pct": round(reward_2 / entry * 100, 1),
            "risk": round(risk, 2),
            "reward_1": round(reward_1, 2),
            "reward_2": round(reward_2, 2),
            "R_R_1": f"{r1:.2f}:1",
            "R_R_2": f"{r2:.2f}:1",
        }
        if account > 0 and risk > 0:
            shares = int((account * risk_pct) / risk)
            result["account_risk_pct"] = round(risk_pct * 100, 2)
            result["risk_dollars"] = round(account * risk_pct, 2)
            result["position_size_shares"] = shares
            result["position_value"] = round(shares * entry, 2)
        else:
            result["account_risk_pct"] = round(risk_pct * 100, 2)
        if ma:
            result["ma_used"] = round(ma, 2)
            result["price_vs_ma"] = "above" if price > ma else "below"
            result["stop_vs_ma"] = "above" if stop > ma else "below"
        return result
