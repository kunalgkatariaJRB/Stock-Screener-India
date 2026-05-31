"""
The Heritage Ledger — Daily Refresh Script (v4)
================================================
Changes from v3:
  - Multi-source price fetching: Yahoo (query1) → Yahoo (query2) → NSE Direct API
  - Staggered timing to avoid rate limits (group pause every 10 stocks)
  - Sector balance rule in SYSTEM_PROMPT (prevents all-cautious bias)
  - Uses compress_prev_data to reduce input tokens (keeps MAX_TOKENS_LEDGER at 32000)

Run daily via GitHub Actions. See .github/workflows/refresh.yml.
Required secrets: ANTHROPIC_API_KEY
Optional env var: HERITAGE_MODEL (default: claude-sonnet-4-6)
"""

import os
import sys
import json
import time
import re
import http.cookiejar
import datetime as dt
from urllib.parse import quote
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

# -----------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------

MODEL              = os.environ.get("HERITAGE_MODEL", "claude-sonnet-4-6")
DATA_PATH          = "data.json"
UNIVERSE_PATH      = Path("data/processed/master_universe.json")
MAX_TOKENS_LEDGER  = 32000
MAX_TOKENS_TIER    = 16000
BATCH_SIZE         = 40

MACRO_TICKERS = {
    "^NSEI":    "Nifty 50",
    "^BSESN":   "Sensex",
    "^NSEBANK": "Bank Nifty",
    "INR=X":    "USD/INR",
    "BZ=F":     "Brent Crude (USD)",
    "GC=F":     "Gold (USD/oz)",
    "SI=F":     "Silver (USD/oz)",
}

NEWS_FEEDS = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("BS Markets",   "https://www.business-standard.com/rss/markets-106.rss"),
    ("BS Companies", "https://www.business-standard.com/rss/companies-101.rss"),
    ("ET Markets",   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Mint Markets", "https://www.livemint.com/rss/markets"),
]

# -----------------------------------------------------------------------
# HTTP HELPERS
# -----------------------------------------------------------------------

def http_get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/html, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ! GET failed {url[:60]}: {e}", file=sys.stderr)
        return ""


# -----------------------------------------------------------------------
# PRICE SOURCES — 3-LEVEL WATERFALL
# -----------------------------------------------------------------------

def yahoo_quote(symbol: str) -> dict | None:
    """Try Yahoo Finance on both query1 and query2 endpoints."""
    for host in ["query1", "query2"]:
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?interval=1d&range=5d"
        body = http_get(url)
        if not body:
            continue
        try:
            j = json.loads(body)
            r = j["chart"]["result"][0]
            m = r["meta"]
            price = m.get("regularMarketPrice")
            prev  = m.get("chartPreviousClose") or m.get("previousClose")
            if price is None or prev is None:
                continue
            return {
                "price":            round(price, 2),
                "prev_close":       round(prev, 2),
                "change_pct":       round((price - prev) / prev * 100, 2),
                "currency":         m.get("currency", "INR"),
                "fifty_two_w_high": m.get("fiftyTwoWeekHigh"),
                "fifty_two_w_low":  m.get("fiftyTwoWeekLow"),
                "market_state":     m.get("marketState", "UNKNOWN"),
                "source":           "Yahoo",
            }
        except Exception:
            continue
    return None


def nse_quote(nse_symbol: str) -> dict | None:
    """
    Fetch from NSE India's official API.
    NSE requires a session cookie — we get one by hitting the homepage first.
    Only works for .NS symbols.
    """
    sym = nse_symbol.replace(".NS", "").upper()
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        # Step 1: establish session cookie
        req0 = urllib.request.Request("https://www.nseindia.com/", headers=headers)
        opener.open(req0, timeout=15)
        time.sleep(0.5)
        # Step 2: fetch quote
        req1 = urllib.request.Request(
            f"https://www.nseindia.com/api/quote-equity?symbol={quote(sym)}",
            headers=headers,
        )
        with opener.open(req1, timeout=15) as r:
            body = r.read().decode("utf-8", errors="replace")
        j = json.loads(body)
        pd = j.get("priceInfo", {})
        price = pd.get("lastPrice")
        prev  = pd.get("previousClose")
        if price is None or prev is None:
            return None
        wk52 = pd.get("weekHighLow", {})
        return {
            "price":            round(float(price), 2),
            "prev_close":       round(float(prev), 2),
            "change_pct":       round((float(price) - float(prev)) / float(prev) * 100, 2),
            "currency":         "INR",
            "fifty_two_w_high": wk52.get("max"),
            "fifty_two_w_low":  wk52.get("min"),
            "market_state":     "REGULAR",
            "source":           "NSE",
        }
    except Exception as e:
        print(f"  ! NSE failed {sym}: {e}", file=sys.stderr)
        return None


def fetch_quote(symbol: str) -> dict | None:
    """
    Waterfall: Yahoo (query1+query2) → NSE Direct.
    Adds per-symbol jitter to reduce rate-limit clustering.
    """
    q = yahoo_quote(symbol)
    if q:
        return q
    # NSE fallback for Indian stocks only
    if symbol.endswith(".NS"):
        time.sleep(0.4 + (hash(symbol) % 6) * 0.1)  # 0.4–1.0s jitter
        return nse_quote(symbol)
    return None


# -----------------------------------------------------------------------
# NEWS + DATA HELPERS
# -----------------------------------------------------------------------

def fetch_news() -> list[dict]:
    items = []
    for src, url in NEWS_FEEDS:
        body = http_get(url, timeout=15)
        if not body:
            continue
        try:
            root = ET.fromstring(body)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                if not title:
                    continue
                title = re.sub(r"<!\[CDATA\[|\]\]>", "", title)
                items.append({"src": src, "title": title})
        except Exception as e:
            print(f"  ! parse {src}: {e}", file=sys.stderr)
    seen, uniq = set(), []
    for it in items:
        k = it["title"][:80].lower()
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq[:60]


def load_existing_data() -> dict:
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_universe() -> dict:
    if not UNIVERSE_PATH.exists():
        print(f"  ! Universe not found at {UNIVERSE_PATH} — run data_ingest.py first", file=sys.stderr)
        return {}
    with open(UNIVERSE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_json_block(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except Exception:
            pass
    raise ValueError("Could not extract JSON from model output")


def compress_prev_data(prev: dict) -> str:
    """Compact summary of previous data.json — saves ~13k input tokens."""
    if not prev:
        return "  (No prior data — first run)"
    lines = []
    lines.append(f"Edition: {prev.get('edition', 'unknown')}")
    lines.append(f"Last updated: {prev.get('lastUpdated', 'unknown')}")
    lines.append(f"Macro narrative: {prev.get('macroNarrative', '')[:300]}")
    lines.append("")
    stocks = prev.get("stocks", {})
    bucket_labels = {
        "conviction": "CONVICTION BUYS",
        "longBets": "INDIA TOMORROW",
        "highPromise": "HIGH PROMISE",
        "watchClose": "HOLD & WATCH",
        "trimAvoid": "TRIM OR AVOID",
    }
    for bucket, label in bucket_labels.items():
        items = stocks.get(bucket, [])
        if not items:
            continue
        lines.append(f"--- {label} ({len(items)}) ---")
        for s in items:
            lines.append(
                f"  {s.get('ticker','?')} | {s.get('name','?')} | "
                f"{s.get('conviction','?')} | {(s.get('thesis') or '')[:120]}"
            )
        lines.append("")
    sectors = prev.get("sectors", [])
    if sectors:
        lines.append("--- SECTORS ---")
        for sec in sectors:
            lines.append(f"  {sec.get('name','?')}: {sec.get('stance','?')} — {sec.get('note','')[:80]}")
        lines.append("")
    whispers = prev.get("whispers", [])
    if whispers:
        lines.append("--- WHISPERS ---")
        for w in whispers:
            if isinstance(w, str):
                lines.append(f"  • {w[:100]}")
            elif isinstance(w, dict):
                lines.append(f"  • {w.get('theme', str(w))[:100]}")
    return "\n".join(lines)


# -----------------------------------------------------------------------
# PROMPT BUILDERS
# -----------------------------------------------------------------------

def fmt_fundamentals(s: dict, q: dict | None) -> str:
    parts = []
    if q:
        parts.append(f"Price ₹{q['price']:,.2f} ({q['change_pct']:+.2f}%) [{q.get('source','?')}]")
        hi = q.get("fifty_two_w_high")
        lo = q.get("fifty_two_w_low")
        if hi and lo and hi > lo:
            pos = round((q["price"] - lo) / (hi - lo) * 100)
            parts.append(f"52w {lo}–{hi} [{pos}% of range]")
    elif s.get("price"):
        parts.append(f"Price ₹{s['price']:,.2f} [CSV]")
    if s.get("roce") is not None:
        r = f"ROCE {s['roce']:.1f}%"
        if s.get("roce_5yr"):
            r += f" (5yr {s['roce_5yr']:.1f}%)"
        elif s.get("roce_3yr"):
            r += f" (3yr {s['roce_3yr']:.1f}%)"
        parts.append(r)
    if s.get("pe") is not None:
        parts.append(f"P/E {s['pe']:.1f}x")
    # EPS — actual reported, used for exit target calculations
    if s.get('eps_ttm') is not None and s['eps_ttm'] > 0:
        eps_str = f"EPS ₹{s['eps_ttm']:.2f} (TTM)"
        g = s.get('eps_growth_3yr')
        if g is not None:
            eps_str += f" | EPS 3yr CAGR {g:+.1f}%"
        parts.append(eps_str)
    # Sector from Screener (more accurate than our tags)
    if s.get('sector'):
        parts.append(f"Sector: {s['sector']}")
    # TTM result date — tells Claude how fresh the data is
    if s.get('ttm_result_date'):
        parts.append(f"Results: {s['ttm_result_date']}")
    if s.get("price_to_book") is not None:
        parts.append(f"P/B {s['price_to_book']:.1f}x")
    if s.get("div_yield") is not None and s["div_yield"] > 0:
        parts.append(f"Div {s['div_yield']:.1f}%")
    mc = s.get("market_cap_cr")
    if mc:
        parts.append(f"MCap ₹{mc/100000:.1f}L Cr" if mc >= 100000 else f"MCap ₹{mc/1000:.0f}K Cr" if mc >= 1000 else f"MCap ₹{mc:.0f} Cr")
    pg = s.get("profit_growth_qtr")
    if pg is not None:
        parts.append(f"Qtr profit Δ {pg:+.0f}%{'⚠' if abs(pg) > 150 else ''}")
    sg = s.get("sales_growth_qtr")
    if sg is not None:
        parts.append(f"Qtr sales Δ {sg:+.0f}%{'⚠' if abs(sg) > 200 else ''}")
    if s.get("is_red_flagged"):
        parts.append("🔴 RED FLAGGED")
    elif s.get("caution_note"):
        parts.append(f"⚠ {s['caution_note']}")
    return " | ".join(parts)


def build_tier_prompt(tier_name, tier_label, stocks, price_lookup, macro_block, today_pretty):
    lines = []
    for s in stocks:
        sym = s.get("symbol")
        q = price_lookup.get(sym) if sym else None
        lines.append(f"  • {s['name']} | {s.get('tier','?')} | {fmt_fundamentals(s, q)}")
    stock_block = "\n".join(lines)
    return f"""Today is {today_pretty} IST.

== MACRO SNAPSHOT ==
{macro_block}

== YOUR TASK ==
Analyze {len(stocks)} Indian-listed stocks for the Heritage Ledger "{tier_label}" tier.
These passed rigorous Screener.in quantitative screens (real 5-year ROCE, growth, debt, promoter data).

Apply Graham-Buffett-Munger-Naval:
- Graham: margin of safety, business durability
- Buffett: wonderful business at fair price
- Munger: inversion — no obvious stupidity
- Naval: asymmetric upside, long-term promoter alignment

⚠ quarterly growth spikes >150% may be one-time — flag in your analysis.
🔴 RED FLAGGED stocks should be marked AVOID.

== STOCKS ==
{stock_block}

== OUTPUT ==
Return ONLY this JSON:
{{
  "tier": "{tier_name}",
  "analyzed_at": "{today_pretty}",
  "stocks": [
    {{
      "name": "exact name as given",
      "stance": "pos|neu|neg",
      "conviction": "High|Medium|Low",
      "label": "e.g. Constructive · High",
      "thesis": "2-3 specific sentences referencing actual ROCE/growth numbers. No generic statements.",
      "catalyst": "One sentence — most important driver.",
      "risk": "One sentence — most important risk.",
      "horizon": "e.g. 3-5 yrs",
      "quality_flag": "QUALITY|CAUTION|AVOID",
      "flag_reason": null,
      "exit_targets": {{
        "entry_zone_max": <₹ price for entry>,
        "entry_note": "<one line on current vs entry zone>",
        "fair_value": <₹ intrinsic value estimate>,
        "target_1": <₹ first partial exit>,
        "target_2": <₹ second partial exit>,
        "full_exit": <₹ full position close>,
        "margin_of_safety_pct": <integer>,
        "upside_to_t1_pct": <integer>,
        "thesis_break_triggers": ["<specific condition 1>", "<condition 2>", "<condition 3>"]
      }}
    }}
  ]
}}

Exit target guide:
- fair_value: normalized earnings × sector P/E (compounders 22-30×, growth 25-35×, value 12-18×)
- entry_zone_max: fair_value × 0.75 (compounders) or × 0.65 (small-caps)
- target_1: fair_value × 1.20 | target_2: fair_value × 1.40 | full_exit: fair_value × 1.65
- thesis_break_triggers: SPECIFIC and MEASURABLE only
- For AVOID quality_flag stocks: set all exit_targets values to null
Output ONLY the JSON object, no prose."""


# -----------------------------------------------------------------------
# SYSTEM PROMPTS
# -----------------------------------------------------------------------

SYSTEM_PROMPT = """You are the editor of "The Heritage Ledger", a fundamentals-first \
investment dashboard for a long-term Indian-equity family corpus.

You apply Graham, Buffett, Munger, Naval principles. You are honest. \
Verdicts stay stable unless something fundamental has actually changed.

You output ONE valid JSON object. No prose, no code fences.

INVESTMENT FRAMEWORK:
- Compounders: ROCE >18% sustained, clean balance sheet, durable moat, 5-10yr hold
- Multibaggers: Small/mid-cap, high growth, improving quality, 3-5yr horizon
- Special Situations: Deep value with specific catalyst, 12-24 month thesis

STOCK LISTS REQUIRED:
  conviction (8-12 picks), longBets (6-10), highPromise (3-6),
  watchClose (4-7), trimAvoid (3-6)

Each stock needs these exact fields:
  symbol, ticker, name, sector, thesis, catalysts (list of strings),
  risks (list of strings), fundamentals (pe, pb, roe, div, mcap),
  horizon, conviction, verdict,
  exit_targets (object — see schema below)

EXIT TARGETS SCHEMA — required for every stock in conviction, longBets, highPromise:
{
  "entry_zone_max": <price in ₹ — max you would pay for a new position>,
  "entry_note": <one line — e.g. "Attractive below ₹820, at fair value now">,
  "fair_value": <your intrinsic value estimate in ₹>,
  "target_1": <₹ — first partial exit, 25% of position, typically fair_value × 1.20>,
  "target_2": <₹ — second partial exit, another 25%, typically fair_value × 1.40>,
  "full_exit": <₹ — close the position entirely, typically fair_value × 1.65>,
  "margin_of_safety_pct": <integer — ((entry_zone_max - current_price) / current_price) × 100. Positive = cheap, negative = above entry zone>,
  "upside_to_t1_pct": <integer — ((target_1 - current_price) / current_price) × 100>,
  "thesis_break_triggers": [
    "<specific measurable condition that would invalidate the thesis>",
    "<second condition>",
    "<third condition>"
  ]
}

EXIT TARGET CALCULATION GUIDE:
- fair_value: Use actual EPS (TTM) provided in fundamentals × sector P/E.
  If EPS TTM is provided, use it directly. If not, estimate as Price / P/E.
  Compounders (ROCE>20%): 22-30× EPS. Growth stocks: 25-35× EPS. Value: 12-18× EPS.
  For banks/financials: use P/B (quality private banks: 2.5-3.5× book).
  For multibaggers: project EPS forward using EPS 3yr CAGR provided.
    Forward EPS (3yr) = EPS_TTM × (1 + eps_growth_3yr/100)^3
    Fair Value = Forward EPS × exit_multiple (use conservative 25-30×)
    Present Value = Fair Value / (1.15)^3   [discounting at 15% required return]
- entry_zone_max: fair_value × 0.75 for compounders (25% margin of safety).
  For higher-risk small caps: fair_value × 0.65.
- target_1: fair_value × 1.20
- target_2: fair_value × 1.40
- full_exit: fair_value × 1.65 OR when thesis fundamentally changes
- thesis_break_triggers: must be SPECIFIC and MEASURABLE (e.g. "ROCE falls below 15% for 2 consecutive quarters", not "business deteriorates")

For watchClose and trimAvoid: exit_targets may be null.

SECTOR BALANCE — CRITICAL RULE:
sectors list needs exactly 12 sectors, stance: pos/neu/neg.
Expected: 4-6 constructive, 3-5 selective, 1-3 cautious. Never all cautious.
Constructive candidates: Defence, Private Banking, Specialty Chemicals, Capital Goods, Healthcare, Renewables.

macroNarrative: 3 sentences. whispers: 5-7 themes. earnings: 7-10 entries."""


USER_TEMPLATE = """Today is {today_pretty} IST.

== MACRO SNAPSHOT ==
{macro_block}

== LATEST HEADLINES ==
{news_block}

== KEY MACRO THEMES ==
- Global conflict risk: Spillover concerns affecting risk appetite
- Brent crude elevated: Direct inflationary pressure on India
- INR near historic lows ~94/USD: Headwind for import-heavy sectors
- RBI has eased; global rates still elevated
- China+1: PLI beneficiaries (EMS, chemicals, defence) = structural tailwind
- FII flows: Monitor daily — major sentiment driver

== PREVIOUS VERDICTS (keep stable unless fundamentals changed) ==
{prev_summary}

== YOUR TASK ==
Generate a complete, fresh data.json for today.

Process:
1. INVERT first — what should be avoided? (Red flags, overvaluation, broken thesis)
2. QUALITY — which businesses have durable ROCE >18% with clean balance sheets?
3. VALUATION — of quality businesses, which offer margin of safety?
4. NARRATIVE — what does today's macro mean for each position?
5. SECTORS — assess each of 12 sectors independently (see sector balance rule)

Keep verdicts stable when fundamentals are stable.
Update when: earnings surprise, management change, structural sector shift, valuation re-rating.

Output the complete data.json JSON object."""


TIER_SYSTEM_PROMPT = """You are the research analyst for "The Heritage Ledger". \
Assess stocks that passed rigorous Screener.in quantitative screens. \
Apply Graham-Buffett-Munger-Naval principles. Be specific — reference actual numbers. \
Never invent data. Output clean JSON only. No prose, no code fences."""


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------

def main():
    print(f"[{dt.datetime.utcnow().isoformat()}Z] Heritage Ledger v4 refresh starting...")
    print(f"  model: {MODEL}")

    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    today = dt.datetime.now(ist)
    today_pretty = today.strftime("%A, %d %B %Y, %H:%M")

    # --- 1. Macro ---
    print("\n[1/6] Fetching macro data...")
    macro_lines = []
    for sym, label in MACRO_TICKERS.items():
        q = fetch_quote(sym)
        time.sleep(0.5)
        if q:
            macro_lines.append(
                f"  {label}: {q['price']:,.2f} ({q['change_pct']:+.2f}%)"
                f" | 52w {q.get('fifty_two_w_low','?')}–{q.get('fifty_two_w_high','?')}"
                f" | src={q.get('source','?')}"
            )
        else:
            macro_lines.append(f"  {label}: unavailable")
    macro_block = "\n".join(macro_lines)
    print(f"  ✓ {sum(1 for l in macro_lines if 'unavailable' not in l)}/{len(MACRO_TICKERS)} macro tickers fetched")

    # --- 2. News ---
    print("\n[2/6] Fetching news headlines...")
    news = fetch_news()
    news_block = "\n".join(f"  • [{n['src']}] {n['title']}" for n in news[:50])
    if not news_block:
        news_block = "  (No headlines — proceed with macro + prior data)"
    print(f"  ✓ {len(news)} headlines")

    # --- 3. Universe + prior data ---
    print("\n[3/6] Loading universe and prior data...")
    universe = load_universe()
    prev = load_existing_data()
    prev_summary = compress_prev_data(prev)

    universe_stocks  = universe.get("universe", {})
    compounders      = universe_stocks.get("compounders", [])
    multibaggers     = universe_stocks.get("multibaggers", [])
    special          = universe_stocks.get("special_situations", [])
    early_quality    = universe_stocks.get("early_quality", [])
    emerging         = universe_stocks.get("emerging_compounders", [])
    inflection       = universe_stocks.get("inflection_watch", [])
    all_stocks       = compounders + multibaggers + special + early_quality + emerging + inflection

    print(f"  ✓ Universe: {len(compounders)} compounders | {len(multibaggers)} multibaggers | "
          f"{len(special)} special | {len(early_quality)} early-quality | "
          f"{len(emerging)} emerging | {len(inflection)} inflection")
    print(f"  ✓ Total: {len(all_stocks)} stocks")

    # --- 4. Live prices — staggered, multi-source ---
    print(f"\n[4/6] Fetching prices for {len(all_stocks)} stocks (Yahoo → NSE fallback)...")
    price_lookup = {}
    yahoo_ok = nse_ok = skipped = 0

    for i, s in enumerate(all_stocks):
        sym = s.get("symbol")
        if not sym or not s.get("symbol_resolved"):
            skipped += 1
            continue
        q = fetch_quote(sym)
        if q:
            price_lookup[sym] = q
            if q.get("source") == "NSE":
                nse_ok += 1
            else:
                yahoo_ok += 1
        # Stagger: pause 2s every 10 stocks, else 0.25s
        if (i + 1) % 10 == 0:
            time.sleep(2.0)
        else:
            time.sleep(0.25)

    total_fetched = yahoo_ok + nse_ok
    print(f"  ✓ Prices: {total_fetched}/{len(all_stocks)} | Yahoo={yahoo_ok} NSE={nse_ok} skipped={skipped}")

    # --- 5. Claude client ---
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ✗ ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # --- 6a. Main ledger ---
    print(f"\n[5/6] Claude — Main Ledger...")
    ledger_msg = USER_TEMPLATE.format(
        today_pretty=today_pretty,
        macro_block=macro_block,
        news_block=news_block,
        prev_summary=prev_summary,
    )
    try:
        ledger_text = ""
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS_LEDGER,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": ledger_msg}],
        ) as stream:
            for chunk in stream.text_stream:
                ledger_text += chunk
            final = stream.get_final_message()
            stop_reason = final.stop_reason
            in_tok = final.usage.input_tokens
            out_tok = final.usage.output_tokens
        print(f"  ✓ {len(ledger_text)} chars | stop={stop_reason} | in={in_tok} out={out_tok}")
        if stop_reason == "max_tokens":
            print("  ✗ Response truncated — hit max_tokens limit.", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"  ✗ Claude API call failed: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)

    # Always log head+tail so we can diagnose structure issues
    print(f"  DEBUG response head: {ledger_text[:300]}", file=sys.stderr)
    print(f"  DEBUG response tail: {ledger_text[-300:]}", file=sys.stderr)

    try:
        new_data = extract_json_block(ledger_text)
    except Exception as e:
        print(f"  ✗ JSON parse failed: {e} — falling back to previous data", file=sys.stderr)
        new_data = prev if prev else {}

    required_top   = ["edition", "lastUpdated", "macroNarrative", "stocks", "sectors", "earnings", "whispers"]
    required_lists = ["conviction", "longBets", "highPromise", "watchClose", "trimAvoid"]
    missing = [k for k in required_top if k not in new_data]
    missing_lists = [k for k in required_lists if k not in new_data.get("stocks", {})]
    if missing or missing_lists:
        print(f"  ✗ Missing keys: {missing + missing_lists} — falling back to previous data", file=sys.stderr)
        print(f"  ✗ Top-level keys returned: {list(new_data.keys())}", file=sys.stderr)
        new_data = prev if prev else {}
        # If prev also has no valid structure, build a minimal shell
        if not new_data or any(k not in new_data for k in required_top):
            print("  ! No valid previous data either — building minimal shell", file=sys.stderr)
            new_data = {
                "edition": today.strftime("Edition %d %b %Y"),
                "lastUpdated": today.isoformat(),
                "macroNarrative": "Data refresh in progress — Claude ledger call failed this run.",
                "stocks": {"conviction": [], "longBets": [], "highPromise": [], "watchClose": [], "trimAvoid": [], "extendedUniverse": []},
                "sectors": [],
                "earnings": [],
                "whispers": [],
            }

    # --- 6b. Tier analysis — all 6 tiers run in parallel ---
    print(f"\n[6/6] Claude — Tier Analysis ({len(all_stocks)} stocks, batches of {BATCH_SIZE}, 6 tiers in parallel)...")

    tier_configs = [
        ("compounders",          "Tier 1 — Compounders",           compounders),
        ("multibaggers",         "Tier 2 — Multibagger Candidates", multibaggers),
        ("special_situations",   "Tier 3 — Special Situations",     special),
        ("early_quality",        "Tier 4 — Early Quality",          early_quality),
        ("emerging_compounders", "Tier 5 — Emerging Compounders",   emerging),
        ("inflection_watch",     "Tier 6 — Inflection Watch",       inflection),
    ]

    def run_tier(tier_key, tier_label, stocks):
        """Process one tier's batches sequentially; called in parallel across tiers."""
        if not stocks:
            return tier_key, []
        batches = [stocks[i:i+BATCH_SIZE] for i in range(0, len(stocks), BATCH_SIZE)]
        tier_results = []
        for batch_num, batch in enumerate(batches):
            prompt = build_tier_prompt(tier_key, tier_label, batch, price_lookup, macro_block, today_pretty)
            try:
                text = ""
                with client.messages.stream(
                    model=MODEL,
                    max_tokens=MAX_TOKENS_TIER,
                    system=TIER_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    for chunk in stream.text_stream:
                        text += chunk
                    final = stream.get_final_message()
                    in_tok = final.usage.input_tokens
                    out_tok = final.usage.output_tokens
                parsed = extract_json_block(text)
                batch_stocks = parsed.get("stocks", [])
                # Enrich with Screener data
                stock_map = {s["name"]: s for s in batch}
                for result in batch_stocks:
                    orig = stock_map.get(result["name"], {})
                    result["screener_data"] = {
                        k: orig.get(k) for k in [
                            "roce", "roce_5yr", "roce_3yr", "pe", "price_to_book",
                            "div_yield", "market_cap_cr", "profit_growth_qtr",
                            "sales_growth_qtr", "is_red_flagged", "caution_note",
                            "symbol", "ticker", "tier",
                        ]
                    }
                tier_results.extend(batch_stocks)
                print(f"    ✓ {tier_label} batch {batch_num+1}/{len(batches)}: {len(batch_stocks)} verdicts | in={in_tok} out={out_tok}")
            except Exception as e:
                print(f"    ! {tier_label} batch {batch_num+1} failed: {e}", file=sys.stderr)
        return tier_key, tier_results

    tiers_output = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(run_tier, tier_key, tier_label, stocks): tier_key
            for tier_key, tier_label, stocks in tier_configs
        }
        for future in as_completed(futures):
            tier_key, results = future.result()
            tiers_output[tier_key] = results
            print(f"  ✓ {tier_key}: {len(results)} total")

    # --- 7. Write ---
    new_data["lastUpdated"] = today.isoformat()
    new_data["stocks"]["extendedUniverse"] = []
    new_data["tiers"] = {
        "last_updated": today.isoformat(),
        "universe_source": "Screener.in Premium",
        "universe_last_refreshed": universe.get("last_updated", "unknown"),
        **tiers_output,
    }

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)

    ledger_counts = {k: len(new_data["stocks"].get(k, [])) for k in required_lists}
    tier_counts = {k: len(tiers_output.get(k, [])) for k in [
        "compounders", "multibaggers", "special_situations",
        "early_quality", "emerging_compounders", "inflection_watch"
    ]}
    print(f"\n  ✓ Written: {DATA_PATH}")
    print(f"    Edition: {new_data.get('edition')}")
    print(f"    Ledger: {ledger_counts}")
    print(f"    Tiers:  {tier_counts}")
    print(f"[done] Heritage Ledger v4 complete.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n✗ Fatal unhandled error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
