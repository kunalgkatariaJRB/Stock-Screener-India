"""
The Heritage Ledger — Daily Refresh Script (v3)
================================================
What changed from v2:
  - Now reads data/processed/master_universe.json (built from Screener.in CSVs)
  - Claude receives REAL fundamentals (ROCE, P/E, growth rates, promoter data)
    instead of stale hand-entered numbers
  - Analyzes three tiers from Screener screens (Compounders, Multibaggers,
    Special Situations) in addition to the editorial high-conviction ledger
  - Output data.json gains a "tiers" section for the dashboard

Run daily via GitHub Actions. See .github/workflows/refresh.yml.

Required secrets: ANTHROPIC_API_KEY
Optional env var: HERITAGE_MODEL (default: claude-sonnet-4-6)
"""

import os
import sys
import json
import time
import re
import datetime as dt
from urllib.parse import quote
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import anthropic

# -----------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------

MODEL          = os.environ.get("HERITAGE_MODEL", "claude-sonnet-4-6")
DATA_PATH      = "data.json"
UNIVERSE_PATH  = Path("data/processed/master_universe.json")
MAX_TOKENS     = 16000
BATCH_SIZE     = 55   # max stocks per Claude tier-analysis call

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
# HTTP + YAHOO HELPERS (unchanged from v2)
# -----------------------------------------------------------------------

def http_get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; HeritageLedgerBot/1.0)",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ! GET failed: {e}", file=sys.stderr)
        return ""


def yahoo_quote(symbol: str) -> dict | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?interval=1d&range=5d"
    body = http_get(url)
    if not body:
        return None
    try:
        j = json.loads(body)
        r = j["chart"]["result"][0]
        m = r["meta"]
        price = m.get("regularMarketPrice")
        prev  = m.get("chartPreviousClose") or m.get("previousClose")
        if price is None or prev is None:
            return None
        return {
            "price":          round(price, 2),
            "prev_close":     round(prev, 2),
            "change_pct":     round((price - prev) / prev * 100, 2),
            "currency":       m.get("currency", "INR"),
            "fifty_two_w_high": m.get("fiftyTwoWeekHigh"),
            "fifty_two_w_low":  m.get("fiftyTwoWeekLow"),
            "market_state":   m.get("marketState", "UNKNOWN"),
        }
    except Exception:
        return None


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
    """Load master_universe.json built by data_ingest.py."""
    if not UNIVERSE_PATH.exists():
        print(f"  ! Universe file not found at {UNIVERSE_PATH}", file=sys.stderr)
        print(f"  ! Run data_ingest.py first or upload CSVs to data/screens/", file=sys.stderr)
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


# -----------------------------------------------------------------------
# PROMPT BUILDERS
# -----------------------------------------------------------------------

def fmt_fundamentals(s: dict, q: dict | None) -> str:
    """
    Build a rich one-line fundamentals string for a Screener stock.
    Combines CSV data (real ratios) with live Yahoo price.
    """
    parts = []

    # Live price
    if q:
        parts.append(f"Price ₹{q['price']:,.2f} ({q['change_pct']:+.2f}%)")
        if q.get("fifty_two_w_low") and q.get("fifty_two_w_high"):
            hi = q["fifty_two_w_high"]
            lo = q["fifty_two_w_low"]
            pos = round((q["price"] - lo) / (hi - lo) * 100) if hi > lo else 0
            parts.append(f"52w {lo}–{hi} [{pos}% of range]")
    elif s.get("price"):
        parts.append(f"Price ₹{s['price']:,.2f} [as of CSV]")

    # Core ratios from Screener
    if s.get("roce") is not None:
        roce_str = f"ROCE {s['roce']:.1f}%"
        if s.get("roce_5yr"):
            roce_str += f" (5yr avg {s['roce_5yr']:.1f}%)"
        elif s.get("roce_3yr"):
            roce_str += f" (3yr avg {s['roce_3yr']:.1f}%)"
        parts.append(roce_str)

    if s.get("pe") is not None:
        parts.append(f"P/E {s['pe']:.1f}x")

    if s.get("price_to_book") is not None:
        parts.append(f"P/B {s['price_to_book']:.1f}x")

    if s.get("div_yield") is not None and s["div_yield"] > 0:
        parts.append(f"Div {s['div_yield']:.1f}%")

    if s.get("market_cap_cr"):
        mc = s["market_cap_cr"]
        if mc >= 100000:
            mcap_str = f"₹{mc/100000:.1f}L Cr"
        elif mc >= 1000:
            mcap_str = f"₹{mc/1000:.0f}K Cr"
        else:
            mcap_str = f"₹{mc:.0f} Cr"
        parts.append(f"MCap {mcap_str}")

    # Growth signals
    if s.get("profit_growth_qtr") is not None:
        growth = s["profit_growth_qtr"]
        flag = " ⚠" if abs(growth) > 150 else ""
        parts.append(f"Qtr profit Δ {growth:+.0f}%{flag}")

    if s.get("sales_growth_qtr") is not None:
        growth = s["sales_growth_qtr"]
        flag = " ⚠" if abs(growth) > 200 else ""
        parts.append(f"Qtr sales Δ {growth:+.0f}%{flag}")

    # Red flag or caution
    if s.get("is_red_flagged"):
        parts.append("🔴 RED FLAGGED — passes positive screen but also on avoid list")
    elif s.get("caution_note"):
        parts.append(f"⚠ NOTE: {s['caution_note']}")

    return " | ".join(parts)


def build_tier_prompt(
    tier_name: str,
    tier_label: str,
    stocks: list[dict],
    price_lookup: dict,
    macro_block: str,
    today_pretty: str,
) -> str:
    lines = []
    for s in stocks:
        sym = s.get("symbol")
        q = price_lookup.get(sym) if sym else None
        fund_line = fmt_fundamentals(s, q)
        lines.append(f"  • {s['name']} | {s.get('tier','?')} | {fund_line}")

    stock_block = "\n".join(lines)
    count = len(stocks)

    return f"""Today is {today_pretty} IST.

== MACRO SNAPSHOT ==
{macro_block}

== YOUR TASK ==
Analyze the following {count} Indian-listed stocks for the Heritage Ledger's
"{tier_label}" tier. These passed our rigorous quantitative screens from
Screener.in with real 5-year ROCE, growth, debt, and promoter data.

For each stock, apply the Graham-Buffett-Munger-Naval framework:
- Graham: Is there margin of safety? Is the business durable?
- Buffett: Is it a wonderful business at a fair price?
- Munger: Does it pass the inversion test — no obvious stupidity?
- Naval: Is there asymmetric upside? Is the promoter a long-term player?

Note: stocks marked ⚠ or 🔴 need extra scrutiny in your analysis.
Quarterly growth spikes >150% flagged with ⚠ may be one-time.

== STOCKS TO ANALYZE ==
{stock_block}

== OUTPUT FORMAT ==
Return ONLY a valid JSON object:
{{
  "tier": "{tier_name}",
  "analyzed_at": "{today_pretty}",
  "stocks": [
    {{
      "name": "exact name as given",
      "stance": "pos" | "neu" | "neg",
      "conviction": "High" | "Medium" | "Low",
      "label": "e.g. Constructive · High | Cautious · Low | Watching · Medium",
      "thesis": "2-3 specific sentences applying our principles. Reference actual ROCE/growth numbers given. No generic statements.",
      "catalyst": "One specific sentence — the most important thing that would drive this higher.",
      "risk": "One specific sentence — the most important thing that could break the thesis.",
      "horizon": "e.g. 3-5 yrs | 12-18 months | 5-10 yrs",
      "quality_flag": "QUALITY" | "CAUTION" | "AVOID",
      "flag_reason": "null if QUALITY, else brief reason for CAUTION or AVOID"
    }}
  ]
}}

Rules:
- Mark is_red_flagged stocks as quality_flag: "AVOID"
- Mark caution_note stocks as quality_flag: "CAUTION"
- Be specific — reference the actual numbers given
- If quarterly growth is flagged ⚠, investigate whether it appears sustainable
- Don't invent numbers not provided
- Output ONLY the JSON object, no prose"""


# -----------------------------------------------------------------------
# MAIN LEDGER PROMPT (existing, now enriched with macro context)
# -----------------------------------------------------------------------

SYSTEM_PROMPT = """You are the editor of "The Heritage Ledger", a fundamentals-first \
investment dashboard for a long-term Indian-equity family corpus.

You think in cycles, not quarters. You apply the principles of:
- Benjamin Graham: Mr. Market, margin of safety, business durability
- Warren Buffett: wonderful business at fair price, circle of competence, time as ally
- Charlie Munger: concentration with conviction, inversion (avoid stupidity first)
- Naval Ravikant: asymmetric upside, non-consensus and right, compound interest in everything

You are honest. You never invent fundamentals. If verdicts don't need to change
because nothing fundamental has changed, you keep them steady.

You output ONE valid JSON object matching the previous data.json schema.
No prose, no code fences. The dashboard parses this directly.

INVESTMENT FRAMEWORK (apply to every verdict):
Tier 1 Compounders: ROCE >18% sustained, clean balance sheet, durable moat, 5-10yr hold
Tier 2 Multibaggers: Small/mid-cap, high growth, improving quality, 3-5yr horizon
Tier 3 Special Situations: Deep value with specific catalyst, 12-24 month thesis
Macro Plays: Sector/theme positions driven by macro regime shifts

Stock lists must include:
  conviction (8-12 large/mid-cap high-conviction picks),
  longBets (6-10 small/micro-cap multi-year wagers),
  highPromise (3-6 speculative watch names),
  watchClose (4-7 quality holds at stretched valuations),
  trimAvoid (3-6 names to reduce or avoid).

Each stock must have: symbol, ticker, name, sector, thesis, catalysts, risks,
fundamentals (pe, pb, roe, div, mcap), horizon, conviction, verdict.

The macroNarrative is ~3 sentences on the current Indian-equity environment.
The whispers list is 5-7 themes/catalysts being tracked.
The sectors list has exactly 12 sectors with stance and one-line note.
The earnings list shows next 7-10 calendar entries."""


USER_TEMPLATE = """Today is {today_pretty} IST.

== MACRO SNAPSHOT ==
{macro_block}

== LATEST HEADLINES ==
{news_block}

== GEOPOLITICAL & MACRO CONTEXT ==
Key themes to weave into your macro narrative and sector views:
- Global conflict risk: Multiple heads of government anticipating cross-border crisis spillovers
- Energy markets: Elevated crude prices (Brent >$100) with direct India inflationary impact
- Currency: INR near historic lows (~94/USD) — headwind for import-heavy businesses
- Rate cycle: RBI has eased; global rates still elevated — watch capex-heavy sectors
- China+1: PLI scheme beneficiaries (EMS, chemicals, defence) remain strong structural theme
- FII flows: Monitor daily — sentiment driver even when fundamentals are unchanged

== PREVIOUS DATA.JSON (your prior thinking) ==
{prev_json}

== YOUR TASK ==
Generate a fresh, complete data.json for today.

Apply the Heritage Ledger framework:
1. First pass — INVERT: which stocks/sectors should be avoided? Apply Red Flags
2. Second pass — QUALITY: which businesses have durable ROCE >18% with clean balance sheets?
3. Third pass — VALUATION: of the quality businesses, which have margin of safety?
4. Fourth pass — NARRATIVE: what does the macro context mean for each position?

Update only what has meaningfully changed. Keep verdicts stable when fundamentals are stable.
Flag any earnings surprises or sector developments from the headlines.

Output the complete data.json JSON object."""


TIER_SYSTEM_PROMPT = """You are the research analyst for "The Heritage Ledger", \
a fundamentals-first Indian equity investment system.

Your job is to assess stocks that have passed rigorous quantitative screening \
(ROCE, growth, debt, promoter data from Screener.in) and provide a \
fundamentals-based verdict for each.

You apply Graham-Buffett-Munger-Naval principles. You are specific — you \
reference the actual numbers provided. You never invent data.

You output clean JSON only. No prose, no code fences."""


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------

def main():
    print(f"[{dt.datetime.utcnow().isoformat()}Z] Heritage Ledger v3 refresh starting...")
    print(f"  model: {MODEL}")

    # IST timestamp
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    today = dt.datetime.now(ist)
    today_pretty = today.strftime("%A, %d %B %Y, %H:%M")

    # --- 1. Macro ---
    print("\n[1/6] Fetching macro data...")
    macro_lines = []
    for sym, label in MACRO_TICKERS.items():
        q = yahoo_quote(sym)
        time.sleep(0.3)
        if q:
            macro_lines.append(
                f"  {label}: ₹{q['price']:,.2f} ({q['change_pct']:+.2f}%)"
                f"  | 52w {q.get('fifty_two_w_low','?')}–{q.get('fifty_two_w_high','?')}"
                f"  | state={q['market_state']}"
            )
        else:
            macro_lines.append(f"  {label}: unavailable")
    macro_block = "\n".join(macro_lines)
    print(f"  ✓ {len(macro_lines)} macro tickers")

    # --- 2. News ---
    print("\n[2/6] Fetching news headlines...")
    news = fetch_news()
    news_block = "\n".join(f"  • [{n['src']}] {n['title']}" for n in news[:50])
    if not news_block:
        news_block = "  (No headlines this run — proceed with macro + prior data)"
    print(f"  ✓ {len(news)} headlines")

    # --- 3. Load universe & prior data ---
    print("\n[3/6] Loading universe and prior data...")
    universe = load_universe()
    prev     = load_existing_data()
    prev_json = json.dumps(prev, indent=2)

    universe_stocks = universe.get("universe", {})
    compounders      = universe_stocks.get("compounders", [])
    multibaggers     = universe_stocks.get("multibaggers", [])
    special          = universe_stocks.get("special_situations", [])
    all_tier_stocks  = compounders + multibaggers + special
    print(f"  ✓ Universe: {len(compounders)} compounders, {len(multibaggers)} multibaggers, {len(special)} special situations")
    print(f"  ✓ Prior data: {len(prev_json)} chars")

    # --- 4. Fetch live prices for all universe stocks ---
    print(f"\n[4/6] Fetching live prices for {len(all_tier_stocks)} universe stocks...")
    price_lookup = {}
    for s in all_tier_stocks:
        sym = s.get("symbol")
        if sym and s.get("symbol_resolved"):
            q = yahoo_quote(sym)
            if q:
                price_lookup[sym] = q
            time.sleep(0.12)
    print(f"  ✓ Prices fetched: {len(price_lookup)}/{len(all_tier_stocks)}")

    # --- 5. API client ---
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ✗ ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # --- 6a. CALL 1: Main ledger refresh ---
    print(f"\n[5/6] Calling Claude — Main Ledger...")
    ledger_msg = USER_TEMPLATE.format(
        today_iso=today.isoformat(),
        today_pretty=today_pretty,
        macro_block=macro_block,
        news_block=news_block,
        prev_json=prev_json,
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": ledger_msg}],
    )
    ledger_text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    print(f"  ✓ Ledger response: {len(ledger_text)} chars | tokens in={resp.usage.input_tokens} out={resp.usage.output_tokens}")

    try:
        new_data = extract_json_block(ledger_text)
    except Exception as e:
        print(f"  ✗ Ledger JSON parse failed: {e} — keeping previous", file=sys.stderr)
        sys.exit(1)

    # Validate
    required_top = ["edition", "lastUpdated", "macroNarrative", "stocks", "sectors", "earnings", "whispers"]
    required_stock_lists = ["conviction", "longBets", "highPromise", "watchClose", "trimAvoid"]
    missing = [k for k in required_top if k not in new_data]
    missing_lists = [k for k in required_stock_lists if k not in new_data.get("stocks", {})]
    if missing or missing_lists:
        print(f"  ✗ Missing keys {missing + missing_lists} — keeping previous", file=sys.stderr)
        sys.exit(1)

    # --- 6b. CALL 2+: Tier analysis (Screener stocks in batches) ---
    print(f"\n[6/6] Calling Claude — Tier Analysis ({len(all_tier_stocks)} stocks in batches of {BATCH_SIZE})...")

    tier_configs = [
        ("compounders",       "Tier 1 — Compounders",       compounders),
        ("multibaggers",      "Tier 2 — Multibagger Candidates", multibaggers),
        ("special_situations","Tier 3 — Special Situations", special),
    ]

    tiers_output = {}

    for tier_key, tier_label, stocks in tier_configs:
        if not stocks:
            tiers_output[tier_key] = []
            continue

        print(f"  → {tier_label}: {len(stocks)} stocks...")
        tier_results = []

        # Split into batches
        batches = [stocks[i:i+BATCH_SIZE] for i in range(0, len(stocks), BATCH_SIZE)]
        for batch_num, batch in enumerate(batches):
            prompt = build_tier_prompt(
                tier_key, tier_label, batch,
                price_lookup, macro_block, today_pretty
            )
            try:
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=TIER_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(b.text for b in resp.content if hasattr(b, "text"))
                parsed = extract_json_block(text)
                batch_stocks = parsed.get("stocks", [])

                # Enrich with the original screener fundamentals
                stock_map = {s["name"]: s for s in batch}
                for result in batch_stocks:
                    orig = stock_map.get(result["name"], {})
                    result["screener_data"] = {
                        k: orig.get(k) for k in
                        ["roce", "roce_5yr", "roce_3yr", "pe", "price_to_book",
                         "div_yield", "market_cap_cr", "profit_growth_qtr",
                         "sales_growth_qtr", "is_red_flagged", "caution_note",
                         "symbol", "ticker", "tier"]
                    }

                tier_results.extend(batch_stocks)
                print(f"    ✓ Batch {batch_num+1}/{len(batches)}: {len(batch_stocks)} verdicts | tokens in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
                time.sleep(1)  # brief pause between calls

            except Exception as e:
                print(f"    ! Batch {batch_num+1} failed: {e}", file=sys.stderr)
                # Continue with other batches
                continue

        tiers_output[tier_key] = tier_results
        print(f"  ✓ {tier_label}: {len(tier_results)} verdicts total")

    # --- 7. Merge and write ---
    new_data["lastUpdated"] = today.isoformat()
    new_data["stocks"]["extendedUniverse"] = []  # deprecated — replaced by tiers
    new_data["tiers"] = {
        "last_updated": today.isoformat(),
        "universe_source": "Screener.in Premium",
        "universe_last_refreshed": universe.get("last_updated", "unknown"),
        **tiers_output,
    }

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)

    print(f"\n  ✓ Written: {DATA_PATH}")
    print(f"    Edition: {new_data.get('edition')}")
    ledger_counts = {k: len(new_data["stocks"].get(k, [])) for k in required_stock_lists}
    tier_counts = {k: len(tiers_output.get(k, [])) for k in ["compounders", "multibaggers", "special_situations"]}
    print(f"    Ledger: {ledger_counts}")
    print(f"    Tiers: {tier_counts}")
    print(f"[done] Heritage Ledger v3 refresh complete.\n")


if __name__ == "__main__":
    main()
