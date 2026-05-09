"""
The Heritage Ledger — Daily Refresh Script
==========================================
Runs once a day (via GitHub Actions). Fetches the current market state and
recent headlines, asks Claude to regenerate the editorial portion of
data.json (verdicts, sector views, earnings calendar, whispers), and writes
the result back to disk.

Set ANTHROPIC_API_KEY in your GitHub repo Secrets. That's the only secret
this script needs.

Cost note: ~₹50–150 per month at one refresh per day, depending on model.
Default model is Claude Sonnet 4.6 (good cost/quality balance).
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

import anthropic
from extended_universe import EXTENDED_UNIVERSE_STOCKS

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

MODEL = os.environ.get("HERITAGE_MODEL", "claude-sonnet-4-6")
DATA_PATH = "data.json"
MAX_OUTPUT_TOKENS = 16000

# Macro tickers we summarise into the prompt
MACRO_TICKERS = {
    "^NSEI": "Nifty 50",
    "^BSESN": "Sensex",
    "^NSEBANK": "Bank Nifty",
    "INR=X": "USD/INR",
    "BZ=F": "Brent crude (USD)",
    "GC=F": "Gold (USD/oz)",
    "SI=F": "Silver (USD/oz)",
}

NEWS_FEEDS = [
    ("Moneycontrol",  "https://www.moneycontrol.com/rss/MCtopnews.xml"),
    ("BS Markets",    "https://www.business-standard.com/rss/markets-106.rss"),
    ("BS Companies",  "https://www.business-standard.com/rss/companies-101.rss"),
    ("ET Markets",    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Mint Markets",  "https://www.livemint.com/rss/markets"),
]

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------

def http_get(url: str, timeout: int = 20) -> str:
    """Plain GET with a normal browser UA. Returns text or empty string."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; HeritageLedgerBot/1.0)",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ! GET {url} failed: {e}", file=sys.stderr)
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
        prev = m.get("chartPreviousClose") or m.get("previousClose")
        if price is None or prev is None:
            return None
        return {
            "price": price,
            "prev_close": prev,
            "change_pct": (price - prev) / prev * 100,
            "currency": m.get("currency", "INR"),
            "fifty_two_w_high": m.get("fiftyTwoWeekHigh"),
            "fifty_two_w_low": m.get("fiftyTwoWeekLow"),
            "market_state": m.get("marketState", "UNKNOWN"),
        }
    except Exception:
        return None


def fetch_news() -> list[dict]:
    """Pull RSS headlines from the configured feeds."""
    items = []
    for src, url in NEWS_FEEDS:
        body = http_get(url, timeout=15)
        if not body:
            continue
        try:
            root = ET.fromstring(body)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                if not title:
                    continue
                # crude clean of CDATA tags
                title = re.sub(r"<!\[CDATA\[|\]\]>", "", title)
                items.append({"src": src, "title": title, "pub": pub})
        except Exception as e:
            print(f"  ! parse {src} failed: {e}", file=sys.stderr)
    # de-dupe by title prefix and take a reasonable sample
    seen = set()
    uniq = []
    for it in items:
        k = it["title"][:80].lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    return uniq[:60]  # cap


def load_existing_data() -> dict:
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"  ! {DATA_PATH} not found — starting fresh", file=sys.stderr)
        return {}


def extract_json_block(text: str) -> dict:
    """
    Claude will sometimes wrap JSON in code fences. Be tolerant.
    Find the largest balanced { ... } block and parse it.
    """
    # try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # strip code fences
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass
    # find first { to last }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except Exception:
            pass
    raise ValueError("Could not extract JSON from model output")


# ----------------------------------------------------------------------
# PROMPT
# ----------------------------------------------------------------------

SYSTEM_PROMPT = """You are the editor of "The Heritage Ledger", a fundamentals-first dashboard that helps a long-term Indian-equity investor make considered decisions for a family corpus. Your job is to update the editorial portion of the dashboard each day based on fresh market data and headlines.

You think in cycles, not quarters. You apply the principles of Benjamin Graham (Mr. Market, margin of safety), Warren Buffett (wonderful business at fair price, circle of competence, time as ally), Charlie Munger (concentration with conviction, sell when thesis breaks), and Naval Ravikant (compound interest in everything, contrarian + patient + informed-optimist, asymmetric upside, long-term games with long-term people).

You are honest. If verdicts barely need to change because the fundamentals haven't changed, you keep them. If an event has shifted the picture (a results miss, a major macro shock, a guidance cut, a sector tailwind solidifying), you update the relevant cards' thesis, catalysts, risks, and conviction. You never invent fundamentals — when the trailing P/E or ROE is unknown to you, you keep the previously-stored value or write it as null.

You output ONE valid JSON object that exactly matches the schema of the previous data.json passed to you. No prose, no code fences, no commentary outside the JSON. The dashboard parses this directly.

Stocks lists must include:
  conviction (8-12 large/mid-cap high-conviction buys),
  longBets (6-10 small/micro-cap multi-year wagers on India's growth),
  highPromise (3-6 mid-cap speculative watch names),
  watchClose (4-7 quality holds at stretched valuations),
  trimAvoid (3-6 names to reduce or avoid).

Each stock must have: symbol (Yahoo .NS suffix), ticker, name, sector, thesis (2-3 sentences max), catalysts (3-4 bullets), risks (3 bullets), fundamentals (pe, pb, roe, div, mcap as a string like "1.3L Cr"), horizon, conviction.

The macroNarrative field is a single ~3-sentence reading of the current Indian-equity environment given the data you've been shown. The whispers list is 5-7 themes / catalysts you're tracking. The sectors list contains exactly the same 12 sectors as before (don't add or remove), only updating the stance ("pos"/"neu"/"neg") and one-line note when warranted. The earnings list shows the next 7-10 calendar entries you're aware of.

The edition label should be e.g. "May 2026 · Daily Refresh — 7 May" so the family can see when this was regenerated."""

USER_TEMPLATE = """Today is {today_iso} ({today_pretty} IST).

== CURRENT MACRO SNAPSHOT ==
{macro_block}

== RECENT HEADLINES (last 24-48h, sampled) ==
{news_block}

== PREVIOUS data.json (your prior thinking — keep what still holds) ==
{prev_json}

Your task: produce the updated data.json for today. Apply the principles in the system prompt. Where fundamentals are unchanged, keep them. Where a recent event changes a thesis or moves a stock between buckets, update accordingly. Make sure the JSON is valid and matches the schema exactly. Output ONLY the JSON object."""


# ----------------------------------------------------------------------
# EXTENDED UNIVERSE — Top 100 small/mid-cap analysis
# ----------------------------------------------------------------------

EXTENDED_SYSTEM_PROMPT = """You are the editor of "The Heritage Ledger", writing a brief read on a list of small/mid-cap Indian stocks NOT in the main ledger.

For each stock, you produce a brief, fundamentals-aware verdict — lighter than the main ledger but still grounded in what you know about the company, its sector, and the macro setup.

You apply Graham, Buffett, Munger, Naval principles. You are honest: if a stock is rich, say so. If it's worth watching, say so. If you genuinely don't have enough conviction either way, say "neutral" with a one-line reason.

You output ONE JSON object: {"extendedUniverse": [...]}. No prose, no code fences.

Each stock entry must have exactly these fields:
  symbol (string, with .NS suffix exactly as given)
  ticker (string, exactly as given)
  name (string, exactly as given)
  sector (string, exactly as given)
  stance (string: "pos" | "neu" | "neg")
  conviction (string, e.g. "Constructive · medium", "Cautious · low", "Watching · medium")
  thesis (string: 2-3 sentences, fundamentals-first, applying our principles)
  catalyst (string: one short sentence — the most important thing that would make this work)
  risk (string: one short sentence — the most important thing that would break it)
  horizon (string: e.g. "12-24 months", "2-3 yrs", "long-term")

Be brief but substantive. No filler. No generic advice. Each thesis must be specific to that company and its current setup."""


def build_extended_user_message(today_pretty: str, macro_block: str, stocks: list[dict], price_lookup: dict) -> str:
    """Build the user message for the extended universe call."""
    stock_lines = []
    for s in stocks:
        q = price_lookup.get(s["symbol"])
        if q:
            stock_lines.append(
                f"  • {s['name']} ({s['ticker']}, {s['symbol']}) — {s['sector']} — "
                f"₹{q['price']:.2f} ({q['change_pct']:+.2f}%), 52w {q.get('fifty_two_w_low', '?')}–{q.get('fifty_two_w_high', '?')}"
            )
        else:
            stock_lines.append(f"  • {s['name']} ({s['ticker']}, {s['symbol']}) — {s['sector']} — price unavailable")
    stock_block = "\n".join(stock_lines)

    return f"""Today is {today_pretty} IST.

== CURRENT MACRO SNAPSHOT ==
{macro_block}

== EXTENDED UNIVERSE (small/mid-cap NSE names beyond the main ledger) ==
{stock_block}

Your task: produce {{"extendedUniverse": [...]}} with one entry per stock above, in the same order. Apply our editorial principles and write a brief, specific, fundamentals-aware verdict for each. Output ONLY the JSON object."""


def analyze_extended_universe(client, macro_block: str, today_pretty: str, price_lookup: dict) -> list[dict]:
    """Call Claude to analyze the extended universe stocks. Returns a list of entries."""
    print(f"  → analyzing extended universe ({len(EXTENDED_UNIVERSE_STOCKS)} stocks)...")
    user_msg = build_extended_user_message(today_pretty, macro_block, EXTENDED_UNIVERSE_STOCKS, price_lookup)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=EXTENDED_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    print(f"  ✓ extended response received ({len(text)} chars)")
    print(f"    extended usage: input {resp.usage.input_tokens}, output {resp.usage.output_tokens}")

    try:
        parsed = extract_json_block(text)
    except Exception as e:
        print(f"  ✗ extended universe JSON parse failed: {e}", file=sys.stderr)
        return []

    items = parsed.get("extendedUniverse")
    if not isinstance(items, list):
        print(f"  ✗ extendedUniverse missing or wrong type", file=sys.stderr)
        return []

    # Light validation per item
    valid = []
    required_fields = {"symbol", "ticker", "name", "sector", "stance", "conviction", "thesis", "catalyst", "risk"}
    for it in items:
        if not isinstance(it, dict):
            continue
        missing = required_fields - set(it.keys())
        if missing:
            print(f"  ! extended item missing fields {missing}: {it.get('ticker', '?')}", file=sys.stderr)
            continue
        valid.append(it)

    print(f"  ✓ extended universe parsed ({len(valid)}/{len(items)} valid entries)")
    return valid


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print(f"[{dt.datetime.utcnow().isoformat()}Z] Heritage Ledger refresh starting...")
    print(f"  model: {MODEL}")

    # 1. Macro snapshot
    macro_lines = []
    for sym, label in MACRO_TICKERS.items():
        q = yahoo_quote(sym)
        time.sleep(0.3)
        if q:
            macro_lines.append(
                f"  {label} ({sym}): {q['price']:.2f}  "
                f"({q['change_pct']:+.2f}%)  "
                f"52w range {q.get('fifty_two_w_low', '—')}–{q.get('fifty_two_w_high', '—')}  "
                f"state={q['market_state']}"
            )
        else:
            macro_lines.append(f"  {label} ({sym}): unavailable")
    macro_block = "\n".join(macro_lines)
    print(f"  ✓ macro fetched ({len(macro_lines)} tickers)")

    # 2. Headlines
    news = fetch_news()
    news_block = "\n".join(f"  • [{n['src']}] {n['title']}" for n in news[:50])
    if not news_block:
        news_block = "  (RSS feeds returned nothing this run — proceed with macro + prior data only.)"
    print(f"  ✓ news fetched ({len(news)} headlines)")

    # 3. Prior data
    prev = load_existing_data()
    prev_json = json.dumps(prev, indent=2)
    print(f"  ✓ prior data loaded ({len(prev_json)} chars)")

    # 4. Build the user message for main ledger refresh
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))  # IST
    today_pretty = today.strftime("%A, %d %B %Y, %H:%M")
    user_msg = USER_TEMPLATE.format(
        today_iso=today.isoformat(),
        today_pretty=today_pretty,
        macro_block=macro_block,
        news_block=news_block,
        prev_json=prev_json,
    )

    # 5. Validate API key and create client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  ✗ ANTHROPIC_API_KEY not set — cannot proceed.", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # 6. CALL 1: Main ledger refresh
    print(f"  → calling Claude for main ledger ({MODEL})...")
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    print(f"  ✓ main response received ({len(text)} chars)")
    print(f"    main usage: input {resp.usage.input_tokens}, output {resp.usage.output_tokens}")

    # 7. Parse and validate main ledger response
    try:
        new_data = extract_json_block(text)
    except Exception as e:
        print(f"  ✗ main JSON parse failed: {e}", file=sys.stderr)
        print("  ✗ keeping previous data.json", file=sys.stderr)
        sys.exit(1)

    # Light validation
    required_top = ["edition", "lastUpdated", "macroNarrative", "stocks", "sectors", "earnings", "whispers"]
    missing = [k for k in required_top if k not in new_data]
    if missing:
        print(f"  ✗ missing keys: {missing} — keeping previous data.json", file=sys.stderr)
        sys.exit(1)

    required_stock_lists = ["conviction", "longBets", "highPromise", "watchClose", "trimAvoid"]
    missing_lists = [k for k in required_stock_lists if k not in new_data["stocks"]]
    if missing_lists:
        print(f"  ✗ missing stock lists: {missing_lists} — keeping previous data.json", file=sys.stderr)
        sys.exit(1)

    # 8. CALL 2: Extended universe analysis
    # First, fetch live prices for the extended universe (so Claude can see current valuations)
    print(f"  → fetching prices for extended universe ({len(EXTENDED_UNIVERSE_STOCKS)} stocks)...")
    price_lookup = {}
    for s in EXTENDED_UNIVERSE_STOCKS:
        q = yahoo_quote(s["symbol"])
        if q:
            price_lookup[s["symbol"]] = q
        time.sleep(0.15)  # be polite to Yahoo
    print(f"  ✓ prices fetched ({len(price_lookup)}/{len(EXTENDED_UNIVERSE_STOCKS)} successful)")

    try:
        extended = analyze_extended_universe(client, macro_block, today_pretty, price_lookup)
    except Exception as e:
        print(f"  ! extended universe call failed: {e}", file=sys.stderr)
        print(f"  ! falling back to previous extendedUniverse if available", file=sys.stderr)
        extended = (prev.get("stocks") or {}).get("extendedUniverse", [])

    # Always carry over the previous extended universe if the new one is empty
    if not extended:
        extended = (prev.get("stocks") or {}).get("extendedUniverse", [])

    # Merge extended universe into main data
    new_data["stocks"]["extendedUniverse"] = extended

    # Force lastUpdated to now
    new_data["lastUpdated"] = today.isoformat()

    # 9. Write
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(new_data, f, indent=2, ensure_ascii=False)
    print(f"  ✓ wrote {DATA_PATH}")
    print(f"    edition: {new_data.get('edition')}")
    counts = {k: len(new_data['stocks'][k]) for k in required_stock_lists}
    counts["extendedUniverse"] = len(extended)
    print(f"    counts: {counts}")
    print(f"[done] Heritage Ledger refresh complete.")


if __name__ == "__main__":
    main()
