import argparse
from importlib import import_module
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICEBOX_CLIENT_DIR = os.path.join(
    os.path.dirname(BASE_DIR), "ai-drive", "modules", "voicebox", "client"
)
sys.path.insert(0, VOICEBOX_CLIENT_DIR)
voicebox = import_module("voicebox_client")
VOICEBOX_BASE_URL = voicebox.VOICEBOX_BASE_URL
proxyVoiceboxRequest = voicebox.proxyVoiceboxRequest

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
DEFAULT_BACKEND = "http://127.0.0.1:1234"


TOOLS_DIR = os.path.join(os.path.dirname(BASE_DIR), "tools")
MAX_TOOL_ROUNDS = 3
TOOL_HINT = (
    "Tools: for any stock price, entry, stop, target or trade-setup question call yahoo_finance "
    "with the ticker symbol (pass risk as a fraction, e.g. 0.015 for 1.5%). "
    "For a quote request, call get_quote with the ticker. "
    "For general stock information requests, call get_stock_info with the ticker symbol. "
    "Call pennant_pattern when asked to check three chronological swing highs and lows for a pennant. "
    "Use web_search only for news, filings or general web information. "
    "Call tools through the tool-calling interface and never write tool-call JSON in your reply."
)
TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "Get a stock quote and market data for a ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker symbol, e.g. AMZN"},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_info",
            "description": "Get current stock information and market data for a ticker symbol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol, e.g. AAPL"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pennant_pattern",
            "description": "Check whether three chronological swing highs and lows form a narrowing pennant. This pattern check does not establish trade qualification or pattern direction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "high1": {"type": "number", "description": "First swing high, oldest"},
                    "low1": {"type": "number", "description": "First swing low, oldest"},
                    "high2": {"type": "number", "description": "Second swing high"},
                    "low2": {"type": "number", "description": "Second swing low"},
                    "high3": {"type": "number", "description": "Third swing high, newest"},
                    "low3": {"type": "number", "description": "Third swing low, newest"},
                },
                "required": ["high1", "low1", "high2", "low2", "high3", "low3"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for real-time information, news, stock quotes, SEC filings",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "yahoo_finance",
            "description": "Get live stock price, volume, moving averages, 52-week high/low for a ticker symbol, with entry/stop/target trade setup",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker symbol, e.g. ATRC"},
                    "risk": {"type": "number", "description": "Account risk fraction, 0.015 = 1.5% (default 0.015)"},
                    "account": {"type": "number", "description": "Account size in dollars (optional, enables position size)"},
                },
                "required": ["symbol"],
            },
        },
    },
]

TOOL_ALIASES = {
    "get_quote": "yahoo_finance",
    "get_live_data": "yahoo_finance",
    "get_stock_info": "yahoo_finance",
    "get_stock_data": "yahoo_finance",
    "fetch_price": "yahoo_finance",
    # Trade setup is computed inside yahoo_finance, never by the LLM.
    "calculate_triggers": "yahoo_finance",
    "setup": "yahoo_finance",
}

TOOLS = {}
qualify_ticker = None
try:
    sys.path.insert(0, os.path.join(os.path.dirname(BASE_DIR), "ai-drive"))
    qualify_ticker = import_module("trading_checklist").qualify_ticker
except Exception as exc:
    print(f"Ticker qualification disabled: {exc}")
try:
    sys.path.insert(0, TOOLS_DIR)
    _tools = import_module("aladdin_stock_tools").Tools()
    TOOLS = {
        "web_search": _tools.web_search,
        "yahoo_finance": _tools.yahoo_finance,
        "pennant_pattern": _tools.pennant_pattern,
    }
except Exception as exc:
    print(f"Tools disabled: {exc}")


STOCK_WORDS = re.compile(r"\b(entry|stop|target|trigger|setup|price|quote|volume|breakout|ticker|symbol)\b", re.I)
TICKER_FIELD = re.compile(
    r"""["']?(?:ticker|symbol|stock)["']?\s*[:=]\s*["']?([A-Za-z][A-Za-z0-9.-]{0,9})""",
    re.I,
)
RISK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:account\s*)?risk|risk\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%", re.I)
NOT_TICKERS = {"SEC", "ETF", "USD", "AND", "THE", "FOR", "NEWS", "RISK", "STOP", "BUY", "SELL", "PRICE", "ATR", "TICKER", "SYMBOL"}


def extract_ticker(text):
    """Extract a ticker field first, or accept a standalone uppercase symbol."""
    text = (text or "").strip()
    match = TICKER_FIELD.search(text)
    if match:
        return match.group(1).upper()
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,5}", text):
        return text
    return None


def stock_intent(text):
    """Return (symbol, risk_fraction or None) when text is a ticker trade-setup/price question."""
    text = text or ""
    symbol = extract_ticker(text)
    if not symbol and not STOCK_WORDS.search(text):
        return None
    if not symbol:
        symbol = next((t for t in re.findall(r"\b[A-Z]{2,5}\b", text) if t not in NOT_TICKERS), None)
    if not symbol:
        return None
    m = RISK_RE.search(text)
    risk = float(m.group(1) or m.group(2)) / 100 if m else None
    return symbol, risk


def resolve_tool(name, args):
    """Map a (possibly invented) tool name to a real tool, or None to ignore it."""
    name = TOOL_ALIASES.get(name, name)
    if name in TOOLS:
        return name
    if isinstance(args, dict):
        if "symbol" in args or "ticker" in args:
            return "yahoo_finance"
        if "query" in args:
            return "web_search"
    return None


def parse_text_calls(content):
    """Extract {"name": ..., "parameters": ...} objects the model printed as plain text,
    even when surrounded by prose. Returns a list of (name, args), or None."""
    text = content or ""
    decoder = json.JSONDecoder()
    calls, pos = [], 0
    while True:
        pos = text.find("{", pos)
        if pos < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, pos)
        except ValueError:
            pos += 1
            continue
        pos = end
        if not isinstance(obj, dict) or "name" not in obj:
            continue
        args = obj.get("parameters", obj.get("arguments", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        calls.append((str(obj["name"]), args if isinstance(args, dict) else {}))
    return calls or None


def _post_json(base, payload, headers, timeout=120):
    req_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=req_headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


TOOL_TRIGGER = re.compile(
    r"\b(stock|stocks|share|shares|ticker|price|quote|news|search|latest|filing|filings|sec|earnings|market|web|google|lookup|current|today|pennant)\b",
    re.I,
)


def _usd(value):
    return f"${value:,.2f}" if isinstance(value, (int, float)) else "N/A"


def _int(value):
    return f"{int(value):,}" if isinstance(value, (int, float)) else "N/A"


def _ratio(value):
    """Numeric R:R from a number or a string like '1.11:1'."""
    try:
        return float(str(value).split(":")[0])
    except (TypeError, ValueError):
        return None


def format_universal_card(symbol, quote, setup):
    """Markdown card for any ticker, built only from the quote and setup dicts.
    quote: price, prev_close, open, high, low, volume, avg_volume, week_52_high, week_52_low,
           ma_20 / ma_50, name.
    setup: status, entry, stop, stop_reason, t1, t2, t1_reason, t2_reason, risk_per_share,
           reward1, reward2, rr1, rr2, note, risk_pct, entry_condition (optional).
    Missing values are shown as N/A. Plain bullets only (no tables)."""
    price, high, low = quote.get("price"), quote.get("high"), quote.get("low")
    volume, avg_volume = quote.get("volume"), quote.get("avg_volume")
    wk_high, wk_low = quote.get("week_52_high"), quote.get("week_52_low")
    entry, t1, t2 = setup.get("entry"), setup.get("t1"), setup.get("t2")

    def gain(target):
        return f"{(target / entry - 1) * 100:+.1f}%" if target and entry else "N/A"

    # === STOPLIGHTS (generic, from the quote only) ===
    ma20 = quote.get("ma_20") or quote.get("ma_50")
    ma50 = quote.get("ma_50") or ma20
    if price is None or not ma20:
        trend_light, trend_note = "⚪ N/A", "No moving-average data"
    elif price > ma20 and price > ma50:
        trend_light = "🟢 UPTREND"
        trend_note = f"Price {_usd(price)} > 20D {_usd(ma20)} and 50D {_usd(ma50)}"
    elif price > ma20 or price > ma50:
        trend_light = "🟡 MIXED"
        trend_note = f"Price between the MAs — 20D {_usd(ma20)}, 50D {_usd(ma50)}"
    else:
        trend_light = "🔴 DOWNTREND"
        trend_note = f"Price {_usd(price)} < 20D {_usd(ma20)} and 50D {_usd(ma50)}"

    if price is None or wk_high is None or wk_low is None:
        range_light, range_note = "⚪ N/A", "No 52-week data"
    else:
        pct_from_high = (price / wk_high - 1) * 100 if wk_high else 0.0
        pct_range = (price - wk_low) / (wk_high - wk_low) * 100 if wk_high != wk_low else 50
        range_light = (
            "🟢 Near High" if pct_range >= 80
            else "🟡 Mid Range" if pct_range >= 50
            else "🔴 Near Low"
        )
        range_note = (
            f"{pct_range:.0f}% of range ({_usd(wk_low)} – {_usd(wk_high)}), "
            f"{pct_from_high:+.1f}% from high"
        )

    if volume is None or not avg_volume:
        vol_light, vol_note = "⚪ N/A", "No volume data"
    else:
        vol_ratio = volume / avg_volume
        vol_light = (
            "🟢 Confirmed" if vol_ratio >= 0.8
            else "🟡 Light" if vol_ratio >= 0.5
            else "🔴 Weak"
        )
        vol_note = f"{_int(volume)} = {vol_ratio * 100:.0f}% of avg {_int(avg_volume)}"

    day_range = f"{_usd(low)} – {_usd(high)}" if low is not None and high is not None else "N/A"
    range_52w = f"{_usd(wk_low)} – {_usd(wk_high)}"
    risk_pct = setup.get("risk_pct")
    risk_label = f"{risk_pct * 100:.1f}%" if isinstance(risk_pct, (int, float)) else "n/a"
    name = quote.get("name") or symbol
    header_price = f" — {_usd(price)}" if price is not None else ""

    lines = [
        f"### {symbol} — {name}{header_price}",
        "",
        "**STOPLIGHTS:**",
        f"- Trend: {trend_light} — {trend_note}",
        f"- 52-Week: {range_light} — {range_note}",
        f"- Volume: {vol_light} — {vol_note}",
        "",
        "**PRICE ACTION:**",
        f"- Price: {_usd(price)}",
        f"- Day Range: {day_range}",
        f"- Prev Close: {_usd(quote.get('prev_close'))}",
        f"- 20-Day MA: {_usd(quote.get('ma_20') or quote.get('ma_50'))}",
        f"- 50-Day MA: {_usd(quote.get('ma_50') or quote.get('ma_20'))}",
        f"- 52-Week Range: {range_52w}",
        "",
        f"**SETUP: {setup.get('status', 'N/A')} (Risk {risk_label}):**",
    ]

    if entry is None:
        lines.append(f"- {setup.get('note') or 'Setup unavailable.'}")
    else:
        condition = setup.get("entry_condition")
        if not condition:
            need = f" on volume > {int(avg_volume * 0.8):,}" if avg_volume else ""
            condition = f"Close above {_usd(high)}{need}"
        rr1, rr2 = _ratio(setup.get("rr1")), _ratio(setup.get("rr2"))
        verdict = "✅ PASS" if rr1 is not None and rr1 >= 1 else "❌ FAIL"
        rr_text = (
            f"{rr1:.2f}:1 / {rr2:.2f}:1" if rr1 is not None and rr2 is not None else "N/A"
        )
        lines += [
            f"- 🎯 Entry: {_usd(entry)} — {condition}",
            f"- 🛑 Stop: {_usd(setup.get('stop'))} — {setup.get('stop_reason', 'N/A')}",
            f"- 🏁 Target 1: {_usd(t1)} ({gain(t1)})",
            f"- 🚀 Target 2: {_usd(t2)} ({gain(t2)})",
            f"- Risk: {_usd(setup.get('risk_per_share'))}/share",
            f"- Reward: {_usd(setup.get('reward1'))} / {_usd(setup.get('reward2'))}",
            f"- R:R: {rr_text} {verdict}",
        ]
        if setup.get("position_size_shares") is not None:
            lines.append(
                f"- Position: {setup['position_size_shares']:,} shares "
                f"({_usd(setup.get('position_value'))}) — risking {_usd(setup.get('risk_dollars'))}"
            )
        if setup.get("note"):
            lines += ["", f"> {setup['note']}"]

    return "\n".join(lines)


def format_stock_reply(raw):
    """Turn yahoo_finance JSON into a universal card; None if the lookup failed."""
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    s = d.get("setup")
    if "error" in d or not isinstance(s, dict):
        return None
    quote = {
        "name": d.get("name"),
        "price": d.get("currentPrice"),
        "prev_close": d.get("previousClose"),
        "open": d.get("open"),
        "high": d.get("dayHigh"),
        "low": d.get("dayLow"),
        "volume": d.get("volume"),
        "avg_volume": d.get("averageVolume"),
        "week_52_high": d.get("fiftyTwoWeekHigh"),
        "week_52_low": d.get("fiftyTwoWeekLow"),
        "ma_20": d.get("ma_20"),
        "ma_50": d.get("fiftyDayAverage"),
    }
    pct = s.get("account_risk_pct")
    setup = {
        "status": s.get("status"),
        "entry": s.get("entry_trigger"),
        "entry_condition": s.get("entry_condition"),
        "stop": s.get("stop"),
        "stop_reason": s.get("stop_reason"),
        "t1": s.get("target_1"),
        "t1_reason": s.get("target_1_reason"),
        "t2": s.get("target_2"),
        "t2_reason": s.get("target_2_reason"),
        "risk_per_share": s.get("risk"),
        "reward1": s.get("reward_1"),
        "reward2": s.get("reward_2"),
        "rr1": s.get("R_R_1"),
        "rr2": s.get("R_R_2"),
        "note": s.get("summary") or s.get("reason"),
        "risk_pct": pct / 100 if isinstance(pct, (int, float)) else None,
        "position_size_shares": s.get("position_size_shares"),
        "position_value": s.get("position_value"),
        "risk_dollars": s.get("risk_dollars"),
    }
    return format_universal_card(d.get("symbol", ""), quote, setup)


TRADE_WORDS = re.compile(r"\b(entry|stop|target|trigger|setup|breakout|swing|trade|buy|ticker|symbol)\b", re.I)


def qualify_from_text(text):
    """Run the mandatory qualification when the user asks for a trade setup on a ticker.
    Returns (qualify_ticker result, market_data), or (None, None) if not a trade question / data unavailable."""
    ticker = extract_ticker(text)
    if qualify_ticker is None or "yahoo_finance" not in TOOLS:
        return None, None
    if not TRADE_WORDS.search(text or "") and not ticker:
        return None, None
    intent = stock_intent(text)
    if not intent:
        return None, None
    try:
        t_fetch = time.perf_counter()
        try:
            market_data = _tools.qualification_data(intent[0])
        finally:
            print(f"[TIMING] yfinance {intent[0]}: {time.perf_counter() - t_fetch:.1f}s", flush=True)
    except Exception as exc:
        print(f"Qualification data failed for {intent[0]}: {exc}")
        return None, None
    if not market_data:
        return None, None
    t_check = time.perf_counter()
    qual = qualify_ticker(intent[0], market_data, load_settings())
    print(
        f"[TIMING] checklist: {time.perf_counter() - t_check:.1f}s - {qual['status']} {qual['score']}",
        flush=True,
    )
    return qual, market_data


LLM_TIMEOUT_S = 25
LLM_MAX_TOKENS = 300
SETTINGS_PATH = os.path.join(BASE_DIR, "scan_settings.json")
normalize_settings = None
try:
    normalize_settings = import_module("trading_checklist").normalize_settings
except Exception:
    pass


def load_settings():
    """User stop settings (stop_mode, stop_fixed_pct, atr_mult); defaults if none saved."""
    saved = {}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        pass
    return normalize_settings(saved) if normalize_settings else saved


def save_settings(new):
    merged = normalize_settings({**load_settings(), **(new if isinstance(new, dict) else {})})
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2)
    return merged


def trade_levels(data, qual=None):
    """Entry/stop/targets: taken from the checklist result when available, otherwise
    a 2% stop with T1 = 1.5R and T2 = 2.5R."""
    if qual and qual.get("entry_price") and qual.get("stop_price") is not None:
        return {"entry": qual["entry_price"], "stop": qual["stop_price"],
                "t1": qual["target1_price"], "t2": qual["target2_price"]}
    entry = data.get("price")
    if not entry:
        return None
    stop = entry * 0.98
    risk = entry - stop
    return {"entry": entry, "stop": stop, "t1": entry + 1.5 * risk, "t2": entry + 2.5 * risk}


def quick_trade_reply(candidates, payload, headers, qual, data):
    """One short, time-limited LLM call for commentary. The levels card is built in code,
    so a slow or unreachable model never blocks the answer."""
    levels = trade_levels(data, qual)
    card = f"### {qual['ticker']} — ✓ QUALIFIED {qual['score']}\n\n"
    prompt = qualified_system_prompt(qual)
    if levels:
        card += (
            f"- 🎯 Entry: {_usd(levels['entry'])}\n"
            f"- 🛑 Stop: {_usd(levels['stop'])} ({(levels['entry'] - levels['stop']) / levels['entry'] * 100:.1f}% below)\n"
            f"- 🏁 Target 1: {_usd(levels['t1'])} (1.5R)\n"
            f"- 🚀 Target 2: {_usd(levels['t2'])} (2.5R)\n"
        )
        prompt += (
            f" Levels already computed: Entry {levels['entry']:.2f}, Stop {levels['stop']:.2f}, "
            f"Target 1 {levels['t1']:.2f}, Target 2 {levels['t2']:.2f}. "
            "Do not recalculate them. In 3 short bullets, give the trade thesis and the main risk."
        )
    messages = [{"role": "system", "content": prompt}] + list(payload.get("messages", []))[-1:]
    request = {
        "model": payload.get("model", ""),
        "messages": messages,
        "max_tokens": LLM_MAX_TOKENS,
        "temperature": 0.3,
        "stream": False,
    }
    deadline = time.monotonic() + LLM_TIMEOUT_S
    for base in candidates:
        remaining = deadline - time.monotonic()
        if remaining < 1:
            break
        try:
            data_out = _post_json(base, request, headers, timeout=remaining)
            text = ((data_out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if text.strip():
                return f"{card}\n{text.strip()}"
            break
        except (urllib.error.URLError, ValueError, OSError) as exc:
            print(f"[TIMING] Llama call failed on {base}: {exc}", flush=True)
    return f"{card}\n> Model commentary unavailable (timed out after {LLM_TIMEOUT_S}s); levels above are computed from the checklist data."


MAX_SCAN_TICKERS = 50
TICKER_TOKEN = re.compile(r"[A-Z][A-Z0-9.-]{0,4}")


def parse_input(text):
    """Split 'AAPL, MSFT nvda' (commas, spaces, newlines) into unique valid tickers."""
    if isinstance(text, (list, tuple)):
        text = " ".join(str(t) for t in text)
    seen = []
    for token in re.split(r"[,\s]+", str(text or "").upper()):
        if TICKER_TOKEN.fullmatch(token) and token not in seen:
            seen.append(token)
    return seen[:MAX_SCAN_TICKERS]


def _short_reason(check):
    # R/R carries its own full explanation (ATR basis, guard, PASS/FAIL per part).
    text = check.get("detail") or str(check["reason"]).split(" (")[0]
    return f"{check['name']}: {text}"


def build_trade_setup(qual, data):
    """Code-computed setup (levels, R multiples, type, size). None unless QUALIFIED."""
    if not qual["qualified"] or not qual.get("entry_price") or qual.get("stop_price") is None:
        return None
    return {
        "entry": qual["entry_price"], "stop": qual["stop_price"], "stop_pct": qual["stop_pct"],
        "target1": qual["target1_price"], "target2": qual["target2_price"],
        "rr_t1": qual["rr_t1"], "rr_t2": qual["rr_t2"],
        "setup_type": qual["setup_type"], "position_size_1pct": qual["position_size_1pct"],
        "account": qual["account"], "confidence": None, "rationale": None,
        "invalidation": None, "timeframe": None, "warnings": qual.get("warnings", []),
    }


SETUP_JSON = re.compile(r"\{.*\}", re.S)
SETUP_TIMEOUT_S = 90
SETUP_TYPES = ("Bull Flag", "Pennant", "Pullback", "Breakout")
NOTE_KEYS = ("setup_type", "confidence", "rationale", "invalidation", "timeframe")


def _parse_setup_notes(text):
    """Pull the note fields from model output, tolerating wrapper objects
    ({"name":..., "parameters":{...}}) and replies truncated mid-JSON."""
    notes = {}
    match = SETUP_JSON.search(text)
    if match:
        try:
            notes = json.loads(match.group(0))
        except ValueError:
            notes = {}
    if isinstance(notes.get("parameters"), dict):
        notes = notes["parameters"]
    if not isinstance(notes, dict):
        notes = {}
    for key in NOTE_KEYS:
        if not notes.get(key):
            found = re.search(rf'"{key}"\s*:\s*(?:"([^"]*)"|(\d+))', text)
            if found:
                notes[key] = found.group(1) or found.group(2)
    return notes


def llm_setup_notes(candidates, headers, qual, data):
    """One Llama call (model stays loaded) for setup type, confidence, rationale, invalidation
    and timeframe. Price levels always come from the checklist, never from the model."""
    setup = build_trade_setup(qual, data)
    if setup is None:
        return None
    atr_pct = (data.get("atr") or 0) / data["price"] * 100 if data.get("price") else 0
    checks = "; ".join(f"{c['name']} {'PASS' if c['pass'] else 'FAIL'}" for c in qual["checks"])
    prompt = (
        f"Ticker {qual['ticker']} QUALIFIED {qual['score']}. Price {setup['entry']:.2f}, "
        f"SMA50 {data.get('sma50') or 0:.2f}, SMA200 {data.get('sma200') or 0:.2f}, "
        f"RSI {data.get('rsi') or 0:.0f}, ATR {atr_pct:.1f}%, Volume {int(data.get('volume') or 0):,}. "
        f"Stop {setup['stop_pct']:.2f}% T1 {setup['rr_t1']:.2f}R. Checklist: {checks}. "
        f"Levels are fixed: Entry {setup['entry']:.2f} Stop {setup['stop']:.2f} "
        f"T1 {setup['target1']:.2f} T2 {setup['target2']:.2f}. "
        "Give JSON: setup_type, confidence 0-100, rationale (1 short sentence), "
        "invalidation (what breaks the setup, short), timeframe (3-10 days)."
    )
    schema = {
        "type": "object",
        "properties": {
            "setup_type": {"type": "string", "enum": list(SETUP_TYPES)},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "rationale": {"type": "string", "maxLength": 120},
            "invalidation": {"type": "string", "maxLength": 80},
            "timeframe": {"type": "string", "maxLength": 20},
        },
        "required": list(NOTE_KEYS),
    }
    request = {"model": "", "messages": [{"role": "user", "content": prompt}],
               "max_tokens": 130, "temperature": 0.2, "stream": False,
               "response_format": {"type": "json_object", "schema": schema}}
    for base in candidates or []:
        try:
            out = _post_json(base, request, headers or {}, timeout=SETUP_TIMEOUT_S)
            text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            notes = _parse_setup_notes(text)
            kind = str(notes.get("setup_type", "")).title()
            if kind in SETUP_TYPES:
                setup["setup_type"] = kind
            try:
                setup["confidence"] = max(0, min(100, int(float(notes.get("confidence")))))
            except (TypeError, ValueError):
                pass
            for key in ("rationale", "invalidation", "timeframe"):
                setup[key] = str(notes.get(key) or "").strip() or None
            break
        except (urllib.error.URLError, ValueError, OSError) as exc:
            print(f"[TIMING] setup notes failed on {base}: {exc}", flush=True)
    return setup


def qualify_and_generate(ticker, candidates=None, headers=None, commentary=False):
    """Qualify one ticker and return a flat, JSON-safe row. Llama is opt-in (commentary=True)
    so a batch scan stays fast; trade_setup numbers are always computed in code."""
    t0 = time.perf_counter()
    row = {"ticker": ticker, "status": "ERROR", "score": "0/8", "passed": 0, "qualified": False,
           "stop_pct": None, "rr_t1": None, "rr_t2": None, "reason": "", "checks": [],
           "fail_reasons": [], "levels": None, "content": None, "trade_setup": None}
    try:
        if qualify_ticker is None or "yahoo_finance" not in TOOLS:
            raise RuntimeError("qualification unavailable")
        market_data = _tools.qualification_data(ticker)
        if not market_data:
            raise RuntimeError("no market data")
        qual = qualify_ticker(ticker, market_data, load_settings())
        cfg = qual.get("settings") or {}
        print(f"[STOP] {ticker} mode={cfg.get('stop_mode')} fixed={cfg.get('stop_fixed_pct')}% "
              f"atr_mult={cfg.get('atr_mult')} => stop {qual['stop_pct']}%", flush=True)
        row.update(
            status=qual["status"], score=qual["score"], qualified=qual["qualified"],
            passed=sum(1 for c in qual["checks"] if c["pass"]),
            stop_pct=qual["stop_pct"], rr_t1=qual["rr_t1"], rr_t2=qual["rr_t2"],
            checks=qual["checks"], fail_reasons=qual["fail_reasons"],
            reason="; ".join(_short_reason(c) for c in qual["checks"] if not c["pass"]),
        )
        if qual["qualified"]:
            row["levels"] = trade_levels(market_data, qual)
            row["trade_setup"] = (
                llm_setup_notes(candidates, headers, qual, market_data) if commentary
                else build_trade_setup(qual, market_data)
            )
        else:
            row["content"] = unqualified_card(qual)
    except Exception as exc:
        row["reason"] = f"Data error: {exc}"
    row["elapsed"] = round(time.perf_counter() - t0, 1)
    print(f"[TIMING] check {ticker}: {row['elapsed']:.1f}s - {row['status']} {row['score']}", flush=True)
    return row


def scan_batch(tickers, candidates=None, headers=None, commentary=False):
    """Qualify every ticker; QUALIFIED first, then by number of passed checks."""
    results = [qualify_and_generate(t, candidates, headers, commentary) for t in tickers]
    results.sort(key=lambda r: (r["qualified"], r["passed"]), reverse=True)
    return results


def unqualified_card(qual):
    reasons = "\n".join(f"- {r}" for r in qual["fail_reasons"])
    why = (
        "a critical check failed (" + "; ".join(qual["critical_fails"]) + ")"
        if qual.get("critical_fails")
        else "it passed fewer than 6 of 8 checklist items"
    )
    return (
        f"### {qual['ticker']} — ✗ UNQUALIFIED {qual['score']}\n\n"
        f"**DO NOT TRADE.** {qual['ticker']}: {why}, "
        f"so no entry, stop or targets are provided.\n\n**FAILED CHECKS:**\n{reasons}"
    )


def qualified_system_prompt(qual):
    passed = ", ".join(c["name"] for c in qual["checks"] if c["pass"]) or "none"
    failed = ", ".join(f"{c['name']} ({c['reason']})" for c in qual["checks"] if not c["pass"]) or "none"
    return (
        f"You are a swing trader. Ticker {qual['ticker']} is QUALIFIED {qual['score']}. "
        f"Use {qual['ticker']} as the authoritative ticker; ignore other tickers in earlier messages "
        "and never use a ticker from a tool-call name. "
        f"Passed: {passed}. Failed: {failed}. "
        "Only provide entry/stop/target if qualified. "
        "Use the stop and targets already computed by the checklist; the stop is 1% to 5% below entry. "
        "Target1 must be at least 1.5x the stop distance above entry. "
        "If you cannot find levels with those constraints, say R/R fails. "
        "If fail_reasons include critical event (earnings, split, FDA), say DO NOT TRADE."
    )


def _completion_bytes(payload, content, qual):
    return json.dumps(
        {
            "object": "chat.completion",
            "model": payload.get("model", ""),
            "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}
            ],
            "qualification": qual,
        }
    ).encode("utf-8")


def _prepare_tool_args(real, args, last_symbol=None, qualified_ticker=None):
    args = dict(args) if isinstance(args, dict) else {}
    if real == "yahoo_finance":
        ticker = args.pop("ticker", None)
        symbol = qualified_ticker or args.get("symbol") or ticker or last_symbol
        if symbol:
            args["symbol"] = symbol
    allowed = TOOLS[real].__code__.co_varnames[1 : TOOLS[real].__code__.co_argcount]
    return {k: v for k, v in args.items() if k in allowed and v not in (None, "", "null", "None")}


def run_tool_loop(candidates, body, headers):
    """Qualify the ticker first (mandatory), then run the tool loop.
    FAIL skips the LLM entirely; PASS injects the checklist into the system prompt."""
    t_total = time.perf_counter()
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return None
    if payload.get("stream") or "tools" in payload:
        return None
    user_text = next(
        (str(m.get("content", "")) for m in reversed(payload.get("messages", [])) if m.get("role") == "user"),
        "",
    )
    qual, market_data = qualify_from_text(user_text)
    if qual is None:
        return _run_tool_loop(candidates, body, headers)
    if not qual["qualified"]:
        print(f"[TIMING] TOTAL: {time.perf_counter() - t_total:.1f}s (no Llama call)", flush=True)
        return _completion_bytes(payload, unqualified_card(qual), qual)
    t_llm = time.perf_counter()
    content = quick_trade_reply(candidates, payload, headers, qual, market_data)
    print(f"[TIMING] Llama 8B: {time.perf_counter() - t_llm:.1f}s", flush=True)
    print(f"[TIMING] TOTAL: {time.perf_counter() - t_total:.1f}s", flush=True)
    return _completion_bytes(payload, content, qual)


def _run_tool_loop(candidates, body, headers, extra_system="", qualified_ticker=None):
    """Offer tools to the model and execute any calls. Returns response bytes,
    or None to fall back to plain proxying (streaming, bad body, tools unsupported)."""
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return None
    if payload.get("stream") or "tools" in payload:
        return None

    payload["tools"] = TOOL_SPECS
    hint = f"{TOOL_HINT}\n\n{extra_system}" if extra_system else TOOL_HINT
    messages = [{"role": "system", "content": hint}] + list(payload.get("messages", []))
    last_symbol = None
    user_text = next(
        (str(m.get("content", "")) for m in reversed(payload.get("messages", [])) if m.get("role") == "user"),
        "",
    )
    if not (TOOL_TRIGGER.search(user_text) or stock_intent(user_text)):
        return None
    if len(user_text) <= 200 and "yahoo_finance" in TOOLS and not extra_system:
        intent = stock_intent(user_text)
        if intent:
            args = {"symbol": intent[0]}
            if intent[1]:
                args["risk"] = intent[1]
            reply = format_stock_reply(TOOLS["yahoo_finance"](**args))
            if reply:
                return json.dumps(
                    {
                        "object": "chat.completion",
                        "model": payload.get("model", ""),
                        "choices": [
                            {"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": reply}}
                        ],
                    }
                ).encode("utf-8")
    for base in candidates:
        executed = set()
        tool_results = {}
        force_final = False
        try:
            for round_no in range(MAX_TOOL_ROUNDS + 1):
                payload["messages"] = messages
                final_round = force_final or round_no == MAX_TOOL_ROUNDS
                if final_round:
                    payload.pop("tools", None)
                data = _post_json(base, payload, headers)
                message = (data.get("choices") or [{}])[0].get("message", {})
                raw_calls = []
                for call in message.get("tool_calls") or []:
                    fn = call.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    raw_calls.append((call.get("id"), fn.get("name", ""), args))
                structured = bool(raw_calls)
                if not raw_calls:
                    for name, args in parse_text_calls(message.get("content")) or []:
                        raw_calls.append((None, name, args))
                if not raw_calls:
                    return json.dumps(data).encode("utf-8")
                if final_round:
                    final_replies = []
                    for _, name, args in raw_calls:
                        real = resolve_tool(name, args)
                        if real is None:
                            continue
                        args = _prepare_tool_args(real, args, last_symbol, qualified_ticker)
                        key = (real, json.dumps(args, sort_keys=True))
                        if key in tool_results:
                            output = tool_results[key]
                        else:
                            try:
                                output = TOOLS[real](**args)
                            except Exception as exc:
                                output = f"Tool error: {exc}"
                        reply = (
                            format_stock_reply(str(output)) or str(output)
                            if real == "yahoo_finance"
                            else str(output)
                        )
                        if reply:
                            final_replies.append(reply)
                    if final_replies:
                        return _completion_bytes(payload, "\n\n".join(final_replies), None)
                    return json.dumps(data).encode("utf-8")

                resolved = []
                for idx, (call_id, name, args) in enumerate(raw_calls):
                    real = resolve_tool(name, args)
                    if real is None and not structured:
                        continue
                    if real == "web_search":
                        intent = stock_intent(str(args.get("query", ""))) or stock_intent(user_text)
                        if intent:
                            real, args = "yahoo_finance", {"symbol": intent[0]}
                    if real == "yahoo_finance" and "risk" not in args:
                        intent = stock_intent(user_text)
                        if intent and intent[1]:
                            args = {**args, "risk": intent[1]}
                    if real is not None:
                        args = _prepare_tool_args(real, args, last_symbol, qualified_ticker)
                        last_symbol = args.get("symbol", last_symbol)
                    resolved.append((call_id or f"call_{round_no}_{idx}", real, name, args))
                if not resolved:
                    return json.dumps(data).encode("utf-8")

                keys = {(real, json.dumps(args, sort_keys=True)) for _, real, _, args in resolved}
                if keys <= executed:
                    # The model repeated a call it already has results for: make it answer.
                    force_final = True
                    messages.append(
                        {"role": "user", "content": "Using the tool results above, answer the question now in plain text."}
                    )
                    continue
                executed |= keys

                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": cid,
                                "type": "function",
                                "function": {"name": real or name, "arguments": json.dumps(args)},
                            }
                            for cid, real, name, args in resolved
                        ],
                    }
                )
                for cid, real, name, args in resolved:
                    if real is None:
                        output = f"Unknown tool '{name}'. Use web_search or yahoo_finance."
                    else:
                        try:
                            output = TOOLS[real](**args)
                        except Exception as exc:
                            output = f"Tool error: {exc}"
                    tool_results[(real, json.dumps(args, sort_keys=True))] = str(output)
                    messages.append({"role": "tool", "tool_call_id": cid, "content": str(output)})
        except (urllib.error.URLError, ValueError, OSError):
            continue
    return None


class WebUIProxyHandler(SimpleHTTPRequestHandler):
    backend_base = DEFAULT_BACKEND
    fallback_backends = ["http://127.0.0.1:8080", "http://127.0.0.1:1234"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        # Helpful for local debugging and browser fetch stability.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        if self.path.startswith("/v1/"):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            return
        super().do_OPTIONS()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/settings":
            self._send_json(200, load_settings())
            return
        if self.path.startswith("/v1/"):
            self._proxy_request("GET")
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/voicebox/v1/"):
            self._proxy_voicebox_request()
            return
        if self.path.split("?")[0] in ("/api/check", "/api/scan", "/api/setup", "/api/settings"):
            self._handle_api()
            return
        if self.path.startswith("/v1/"):
            self._proxy_request("POST")
            return
        self.send_error(405, "Method Not Allowed")

    def _send_json(self, status, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _forward_headers(self):
        return {
            k: v for k, v in self.headers.items()
            if k.lower() not in {"host", "connection", "content-length", "accept-encoding"}
        }

    def _candidates(self):
        # Try configured backend first, then common local alternatives.
        candidates = [self.backend_base.rstrip("/")]
        for base in self.fallback_backends:
            clean = base.rstrip("/")
            if clean not in candidates:
                candidates.append(clean)
        return candidates

    def _handle_api(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            data = json.loads(self.rfile.read(length) or b"{}") if length > 0 else {}
        except ValueError:
            self._send_json(400, {"error": "Invalid JSON body"})
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "Expected a JSON object"})
            return
        if self.path.split("?")[0] == "/api/settings":
            self._send_json(200, save_settings(data))
            return
        commentary = bool(data.get("commentary")) or self.path.split("?")[0] == "/api/setup"
        candidates, headers = self._candidates(), self._forward_headers()
        if self.path.split("?")[0] in ("/api/check", "/api/setup"):
            tickers = parse_input(data.get("ticker", ""))
            if len(tickers) != 1:
                self._send_json(400, {"error": "Provide exactly one valid ticker"})
                return
            self._send_json(200, qualify_and_generate(tickers[0], candidates, headers, commentary))
            return
        tickers = parse_input(data.get("tickers", ""))
        if not tickers:
            self._send_json(400, {"error": "No valid tickers"})
            return
        self._send_json(200, scan_batch(tickers, candidates, headers, commentary))

    def _proxy_request(self, method):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length > 0 else None

        headers = self._forward_headers()
        candidates = self._candidates()

        if method == "POST" and self.path.split("?")[0] == "/v1/chat/completions" and TOOLS:
            result = run_tool_loop(candidates, body, headers)
            if result is not None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(result)
                return

        errors = []
        for base in candidates:
            target = f"{base}{self.path}"
            req = urllib.request.Request(target, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = resp.read()
                    self.send_response(resp.getcode())
                    for key, value in resp.getheaders():
                        lower = key.lower()
                        if lower in {"transfer-encoding", "connection", "content-encoding"}:
                            continue
                        self.send_header(key, value)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
                    return
            except urllib.error.HTTPError as exc:
                data = exc.read() if exc.fp else b""
                self.send_response(exc.code)
                content_type = exc.headers.get("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                if data:
                    self.wfile.write(data)
                else:
                    payload = {"error": f"Backend HTTP {exc.code}"}
                    self.wfile.write(json.dumps(payload).encode("utf-8"))
                return
            except urllib.error.URLError as exc:
                errors.append({"backend": base, "details": str(exc.reason)})

        self.send_response(502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        payload = {
            "error": "Could not reach local model backend",
            "tried": candidates,
            "details": errors,
        }
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def _proxy_voicebox_request(self):
        endpoint = self.path.removeprefix("/voicebox")
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length > 0 else b""
        content_type = self.headers.get("Content-Type", "")
        if not content_type:
            self.send_error(400, "Content-Type is required")
            return

        try:
            status, response_type, response_body = proxyVoiceboxRequest(
                endpoint,
                body,
                content_type,
            )
        except (RuntimeError, ValueError) as exc:
            payload = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(status)
        self.send_header("Content-Type", response_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response_body)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Serve WebUI and proxy local chat and VoiceBox API calls"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host to bind (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind (default: {DEFAULT_PORT})")
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND,
        help=f"LM Studio backend base URL (default: {DEFAULT_BACKEND})",
    )
    return parser.parse_args()


def _warm_up():
    """Import yfinance at startup so the first scan doesn't pay the ~10-25s cold import."""
    try:
        import_module("yfinance")
    except Exception as exc:
        print(f"yfinance warm-up skipped: {exc}", flush=True)


def main():
    args = parse_args()
    WebUIProxyHandler.backend_base = args.backend.rstrip("/")
    threading.Thread(target=_warm_up, daemon=True).start()

    server = ThreadingHTTPServer((args.host, args.port), WebUIProxyHandler)
    print(f"WebUI server: http://{args.host}:{args.port}/index.html")
    print(f"Proxy /v1/* -> {WebUIProxyHandler.backend_base}/v1/*")
    print(f"Proxy /voicebox/v1/* -> {VOICEBOX_BASE_URL}/v1/*")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
