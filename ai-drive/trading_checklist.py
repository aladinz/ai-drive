"""Mandatory swing-trade ticker qualification checklist (6 of 8 checks must pass).

market_data keys (all optional; a missing value fails the check that needs it):
    price, sma50, sma200, avg_volume_20d, volume, atr, rsi, market_cap, bid, ask,
    lows (daily lows, oldest -> newest, at least 3), high, low, close,
    stop (planned stop price), target1 (or resistance), target2 (optional), events ([{"type": "earnings|split|fda", "date": "YYYY-MM-DD"}]).
"""
from datetime import date, datetime, timedelta

PASS_THRESHOLD = 6
TOTAL_CHECKS = 8
EVENT_WINDOW_TRADING_DAYS = 5
CRITICAL_EVENT_TYPES = ("earnings", "split", "fda")
MIN_REWARD_RISK = 1.5
MIN_STOP_PCT = 1.0
MAX_STOP_PCT = 5.0
MIN_ATR_MULT = 1.0
MAX_ATR_MULT = 1.5
DEFAULT_SETTINGS = {"stop_mode": "fixed", "stop_fixed_pct": 2.0, "atr_mult": 1.2}
LARGE_CAP = 100_000_000_000
SPREAD_FAIL_PCT = 2.0
FALLBACK_T2_R = 2.5
DEFAULT_ACCOUNT = 10_000


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def pennant_pattern(high1, low1, high2, low2, high3, low3):
    """Check three ordered swing highs/lows for converging pennant boundaries.

    The input points must be supplied in chronological order. The pattern's
    direction cannot be inferred without the preceding flagpole.
    """
    values = [high1, low1, high2, low2, high3, low3]
    names = ("high1", "low1", "high2", "low2", "high3", "low3")
    numbers = [_num(value) for value in values]
    if any(value is None for value in numbers):
        missing = [name for name, value in zip(names, numbers) if value is None]
        return {
            "pattern": "PENNANT",
            "detected": False,
            "direction": "undetermined",
            "reason": "Invalid or missing pivot values: " + ", ".join(missing),
        }

    high1, low1, high2, low2, high3, low3 = numbers
    ranges = (high1 - low1, high2 - low2, high3 - low3)
    valid_ranges = all(value > 0 for value in ranges)
    converging = high1 > high2 > high3 and low1 < low2 < low3
    narrowing = valid_ranges and ranges[0] > ranges[1] > ranges[2]
    detected = valid_ranges and converging and narrowing

    if not valid_ranges:
        reason = "Each swing high must be above its corresponding swing low."
    elif detected:
        reason = "Swing highs descend, swing lows ascend, and the range narrows."
    elif not converging:
        reason = "Expected descending swing highs and ascending swing lows."
    else:
        reason = "Expected the swing range to narrow at each pivot."
    return {
        "pattern": "PENNANT",
        "detected": detected,
        "direction": "undetermined",
        "ranges": [round(value, 4) for value in ranges],
        "reason": reason,
    }


def _check(name, passed, value, reason):
    return {"name": name, "pass": bool(passed), "value": value, "reason": reason}


def _missing(name, *fields):
    return _check(name, False, None, "Missing data: " + ", ".join(fields))


def _add_trading_days(start, days):
    current, added = start, 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _trend(d):
    price, sma50, sma200 = _num(d.get("price")), _num(d.get("sma50")), _num(d.get("sma200"))
    if None in (price, sma50, sma200):
        return _missing("TREND", "price", "sma50", "sma200")
    ok = price > sma50 > sma200
    value = f"Price {price:.2f}, SMA50 {sma50:.2f}, SMA200 {sma200:.2f}"
    return _check("TREND", ok, value, "Price > SMA50 > SMA200" if ok else f"Need Price > SMA50 > SMA200 ({value})")


def _volume(d):
    avg, today = _num(d.get("avg_volume_20d")), _num(d.get("volume"))
    if avg is None or today is None:
        return _missing("VOLUME", "avg_volume_20d", "volume")
    est, threshold = _intraday_volume(today)
    ok = avg > 500_000 and est > threshold * avg
    value = (f"20d avg {avg / 1e6:.1f}M, today {today / 1e6:.2f}M, est full-day {est / 1e6:.2f}M "
             f"({est / avg * 100:.0f}% of avg, need >{threshold * 100:.0f}%)")
    need = f"20d avg > 500k and est. volume > {threshold * 100:.0f}% of avg"
    return _check("VOLUME", ok, value, need if ok else f"Need {need} ({value})")


def _eastern_minutes():
    """Minutes since midnight in US Eastern (market clock); weekend flag."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    return now.hour * 60 + now.minute, now.weekday() >= 5


def _intraday_volume(today):
    """Project partial-session volume to a full day; lower the bar before 2pm ET."""
    minutes, weekend = _eastern_minutes()
    if weekend or minutes < 570 or minutes >= 960:
        return today, 0.8
    elapsed = minutes - 570
    est = today / (elapsed / 390) if elapsed > 0 else today
    return est, (0.4 if minutes < 840 else 0.8)


def _volatility(d):
    atr, price = _num(d.get("atr")), _num(d.get("price"))
    if atr is None or not price:
        return _missing("VOLATILITY", "atr", "price")
    pct = atr / price * 100
    ok = 1.5 <= pct <= 5.0
    return _check("VOLATILITY", ok, f"ATR {pct:.2f}%", "ATR% within 1.5%-5%" if ok else f"ATR {pct:.2f}% outside 1.5%-5%")


def _momentum(d):
    rsi = _num(d.get("rsi"))
    if rsi is None:
        return _missing("MOMENTUM", "rsi")
    ok = 45 <= rsi <= 68
    return _check("MOMENTUM", ok, f"RSI {rsi:.1f}", "RSI within 45-68" if ok else f"RSI {rsi:.1f} outside 45-68")


def _liquidity(d):
    cap, bid, ask = _num(d.get("market_cap")), _num(d.get("bid")), _num(d.get("ask"))
    if cap is None:
        return _missing("LIQUIDITY", "market_cap")
    value = f"MarketCap ${cap / 1e9:.2f}B"
    # Only MarketCap can fail a $1B+ name: a real quote with spread <= 2% passes, and a wider
    # spread on a liquid name is stale/crossed bid-ask (n/a, bad data), never a failure.
    if cap > LARGE_CAP:
        value += ", spread n/a (large cap)"
    elif bid and ask and bid > 0 and ask >= bid:
        spread = (ask - bid) / ((ask + bid) / 2) * 100
        if spread > SPREAD_FAIL_PCT:
            value += f", spread n/a (bad data: {spread:.2f}%)"
        else:
            value += f", spread {spread:.3f}%"
    else:
        value += ", spread n/a"
    ok = cap > 1_000_000_000
    return _check("LIQUIDITY", ok, value, "MarketCap > $1B (spread n/a or <= 2%)" if ok else f"Need MarketCap > $1B ({value})")


def _structure(d):
    lows = [_num(x) for x in (d.get("lows") or [])]
    high, low, close = _num(d.get("high")), _num(d.get("low")), _num(d.get("close", d.get("price")))
    if len(lows) < 3 or None in lows[-3:] or None in (high, low, close):
        return _missing("STRUCTURE", "last 3 daily lows", "high", "low", "close")
    higher_lows = lows[-3] < lows[-2] < lows[-1]
    position = (close - low) / (high - low) if high > low else 0.0
    ok = higher_lows or position >= 0.6
    value = f"Higher lows: {'yes' if higher_lows else 'no'}, close at {position * 100:.0f}% of day range"
    return _check("STRUCTURE", ok, value, "Higher lows or close in top 40% of range" if ok else f"Need 3 higher lows or close in top 40% of range ({value})")


def _event(d):
    today = _as_date(d.get("as_of")) or date.today()
    end = _add_trading_days(today, EVENT_WINDOW_TRADING_DAYS)
    hits = []
    for event in d.get("events") or []:
        when = _as_date(event.get("date"))
        kind = str(event.get("type", "event")).lower()
        if when and today <= when <= end:
            hits.append(f"{kind} on {when.isoformat()}")
    if hits:
        return _check("EVENT", False, "; ".join(hits), "Event in next 5 trading days: " + "; ".join(hits))
    return _check("EVENT", True, "None", "No earnings/split/FDA event in next 5 trading days")


def normalize_settings(settings=None):
    """User stop settings: stop_mode 'atr'|'fixed', stop_fixed_pct 1-5, atr_mult 1.5-2.5."""
    s = settings if isinstance(settings, dict) else {}
    mode = str(s.get("stop_mode", DEFAULT_SETTINGS["stop_mode"])).lower()
    fixed = _num(s.get("stop_fixed_pct"))
    mult = _num(s.get("atr_mult"))
    return {
        "stop_mode": mode if mode in ("atr", "fixed") else "atr",
        "stop_fixed_pct": min(MAX_STOP_PCT, max(MIN_STOP_PCT, fixed if fixed is not None else DEFAULT_SETTINGS["stop_fixed_pct"])),
        "atr_mult": min(MAX_ATR_MULT, max(MIN_ATR_MULT, mult if mult is not None else DEFAULT_SETTINGS["atr_mult"])),
    }


def calculate_stop(entry, atr, mode="fixed", fixed_pct=2.0, atr_mult=1.2):
    """Return (stop_pct, stop_price, raw_pct). Fixed mode: fixed_pct; ATR mode: ATR% x multiplier
    (falls back to fixed_pct without ATR). Clamped to the 1-5% guardrail; raw_pct is unclamped."""
    if mode == "fixed" or not atr or not entry:
        raw_pct = fixed_pct
    else:
        raw_pct = (atr / entry) * 100 * atr_mult
    stop_pct = max(MIN_STOP_PCT, min(MAX_STOP_PCT, raw_pct))
    return stop_pct, entry * (1 - stop_pct / 100), raw_pct


def check_rr(entry, stop_price, target1, atr, user_settings=None, target2=None):
    """Stop (ATR-multiple or fixed %, guarded to 1-5%) and Target 1 at least 1.5R.
    The calculated stop is used for validation whenever ATR (or fixed mode) allows it;
    a provided stop_price is only a fallback when ATR is unavailable in ATR mode."""
    cfg = normalize_settings(user_settings)
    entry, stop_price, target1, atr, target2 = _num(entry), _num(stop_price), _num(target1), _num(atr), _num(target2)
    if not entry or entry <= 0:
        return _missing("R/R", "entry")
    mode, mult = cfg["stop_mode"], cfg["atr_mult"]
    if mode == "fixed" or (atr and atr > 0):
        stop_pct, stop_price, raw_pct = calculate_stop(entry, atr or 0, mode, cfg["stop_fixed_pct"], mult)
        if mode == "fixed":
            basis = f"fixed {cfg['stop_fixed_pct']:.1f}%"
        else:
            basis = f"ATR ${atr:.2f} x {mult:g} = {raw_pct:.2f}%"
        if abs(raw_pct - stop_pct) > 1e-9:
            basis += f" clamped to {stop_pct:.2f}%"
    elif stop_price and 0 < stop_price < entry:
        stop_pct = (entry - stop_price) / entry * 100
        basis = "provided stop, no ATR"
    else:
        return _missing("R/R", "atr", "stop")
    if target1 is None:
        return _missing("R/R", "target1")
    risk = entry - stop_price
    rr_t1 = (target1 - entry) / risk
    rr_t2 = (target2 - entry) / risk if target2 is not None else None
    stop_ok = MIN_STOP_PCT <= stop_pct <= MAX_STOP_PCT
    rr_ok = rr_t1 >= MIN_REWARD_RISK
    t2_text = f", T2 {rr_t2:.2f}R" if rr_t2 is not None else ""
    detail = (
        f"Stop {stop_pct:.2f}% ({basis}, {'in' if stop_ok else 'outside'} 1-5% guard) {'PASS' if stop_ok else 'FAIL'}, "
        f"T1 {rr_t1:.2f}R >={MIN_REWARD_RISK:g}R {'PASS' if rr_ok else 'FAIL'}{t2_text}"
    )
    passed = stop_ok and rr_ok
    return {
        **_check("R/R", passed, detail, detail),
        "detail": detail,
        "stop_pct": stop_pct,
        "stop_price": stop_price,
        "atr_mult": mult if mode == "atr" else None,
        "mode": mode,
        "rr_t1": rr_t1,
        "rr_t2": rr_t2,
        "stop_ok": stop_ok,
        "rr_ok": rr_ok,
    }


def _risk_reward(d):
    return check_rr(
        d.get("price"), d.get("stop"), d.get("target1", d.get("resistance")),
        d.get("atr"), d.get("_settings"), d.get("target2"),
    )


_CHECKS = (_trend, _volume, _volatility, _momentum, _liquidity, _structure, _event, _risk_reward)


def qualify_ticker(ticker, market_data, settings=None):
    """Run the 8-point checklist; PASS needs at least 6 passing checks.
    settings: {stop_mode, stop_fixed_pct, atr_mult} (see normalize_settings)."""
    data = dict(market_data) if isinstance(market_data, dict) else {}
    data["_settings"] = normalize_settings(settings)
    checks = []
    for fn in _CHECKS:
        try:
            checks.append(fn(data))
        except Exception as exc:
            checks.append(_check(fn.__name__.strip("_").upper(), False, None, f"Check error: {exc}"))
    passed = sum(1 for c in checks if c["pass"])
    by_name = {c["name"]: c for c in checks}
    rr = by_name.get("R/R", {})
    # Critical: an upcoming event, or a stop outside the 1-5% guard, vetoes the 6/8 score.
    critical_fails = []
    if "EVENT" in by_name and not by_name["EVENT"]["pass"]:
        critical_fails.append("EVENT: " + by_name["EVENT"]["reason"])
    if rr.get("stop_ok") is False:
        critical_fails.append("R/R: Stop " + f"{rr['stop_pct']:.2f}% outside {MIN_STOP_PCT:g}-{MAX_STOP_PCT:g}%")
    qualified = passed >= PASS_THRESHOLD and not critical_fails
    fail_reasons = [f"{c['name']}: {c['reason']}" for c in checks if not c["pass"]]
    warnings = [f"R/R: T1 {rr['rr_t1']:.2f}R < {MIN_REWARD_RISK:g}R"] if qualified and rr.get("rr_ok") is False else []

    entry = _num(data.get("close", data.get("price"))) or _num(data.get("price"))
    stop_pct = rr.get("stop_pct")
    rr_t1, rr_t2 = rr.get("rr_t1"), rr.get("rr_t2")
    stop_price = target1 = target2 = None
    if entry and stop_pct is not None:
        stop_price = entry * (1 - stop_pct / 100)
        if rr_t1 is not None:
            target1 = entry * (1 + stop_pct / 100 * rr_t1)
        if rr_t2 is None and target1 is not None:
            rr_t2 = max(FALLBACK_T2_R, rr_t1 + 1.0)
        if rr_t2 is not None:
            target2 = entry * (1 + stop_pct / 100 * rr_t2)
    structure = by_name.get("STRUCTURE", {})
    near_high = bool(entry and _num(data.get("target1")) and entry >= 0.98 * _num(data.get("target1")))
    if near_high:
        setup_type = "Breakout"
    elif "Higher lows: yes" in str(structure.get("value")):
        setup_type = "Bull Flag"
    else:
        setup_type = "Pullback"
    account = _num(data.get("account")) or DEFAULT_ACCOUNT
    shares = int(account * 0.01 // (entry - stop_price)) if entry and stop_price and entry > stop_price else None
    return {
        "setup_type": setup_type,
        "position_size_1pct": shares,
        "account": account,
        "ticker": str(ticker or "").upper(),
        "status": "PASS" if qualified else "FAIL",
        "score": f"{passed}/{TOTAL_CHECKS}",
        "qualified": qualified,
        "checks": checks,
        "fail_reasons": fail_reasons,
        "critical_fails": critical_fails,
        "warnings": warnings,
        "stop_pct": stop_pct,
        "entry_price": entry,
        "stop_price": stop_price,
        "target1_price": target1,
        "target2_price": target2,
        "rr_t1": rr_t1,
        "rr_t2": rr_t2,
        "settings": data["_settings"],
    }
