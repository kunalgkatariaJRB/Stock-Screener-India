"""
The Heritage Ledger — Data Ingest Pipeline
==========================================
Reads Screener.in CSV exports from data/screens/, cross-references Red Flag
screens, and builds data/processed/master_universe.json.

Run automatically when CSVs are uploaded (via GitHub Actions), or run manually:
    python data_ingest.py

Output: data/processed/master_universe.json
"""

import os
import json
import csv
import time
import datetime as dt
import urllib.request
import urllib.parse
import sys
from pathlib import Path

# -----------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------

SCREENS_DIR = Path("data/screens")
PROCESSED_DIR = Path("data/processed")
OUTPUT_FILE = PROCESSED_DIR / "master_universe.json"

# -----------------------------------------------------------------------
# NAME → YAHOO SYMBOL MAP
# Built from the Screener screen data we fetched. Maps Screener display
# name → Yahoo Finance symbol (.NS for NSE, .BO for BSE-only)
# Extend this as more stocks appear in your screens.
# -----------------------------------------------------------------------

NAME_TO_SYMBOL = {
    # === SCREEN 1 — COMPOUNDERS ===
    "ICICI AMC":            "ICICIAMC.NS",
    "Gillette India":       "GILLETTE.NS",
    "GE Vernova T&D":       "GVTD.NS",
    "Page Industries":      "PAGEIND.NS",
    "HBL Engineering":      "HBLENGINE.NS",
    "3M India":             "3MINDIA.NS",
    "I R C T C":            "IRCTC.NS",
    "IRCTC":                "IRCTC.NS",
    "Atlanta Electric":     "ATLANTAELE.NS",
    "Nippon Life Ind.":     "NAM-INDIA.NS",
    "Nippon Life India":    "NAM-INDIA.NS",
    "HDFC AMC":             "HDFCAMC.NS",
    "Travel Food":          "TRAVELFOOD.NS",
    "Natl. Aluminium":      "NATIONALUM.NS",
    "National Aluminium":   "NATIONALUM.NS",
    "Cummins India":        "CUMMINSIND.NS",
    "Netweb Technol.":      "NETWEB.NS",
    "Netweb Technologies":  "NETWEB.NS",
    "Inventurus Knowl":     "IKS.NS",
    "Inventurus Knowledge": "IKS.NS",
    "Bharat Electron":      "BEL.NS",
    "BEL":                  "BEL.NS",
    "Force Motors":         "FORCEMOT.NS",
    "Triveni Turbine":      "TRITURBINE.NS",
    "Coal India":           "COALINDIA.NS",
    "Polycab India":        "POLYCAB.NS",
    "Pidilite Inds.":       "PIDILITIND.NS",
    "Pidilite":             "PIDILITIND.NS",
    "International Ge":     "IGIL.NS",
    "Eicher Motors":        "EICHERMOT.NS",
    "Anthem Bioscienc":     "ANTHEM.NS",
    "Anthem Bioscience":    "ANTHEM.NS",
    "Hexaware Tech.":       "HEXT.NS",
    "Hexaware":             "HEXT.NS",

    # === SCREEN 2 — MULTIBAGGERS ===
    "Tips Music":           "TIPSMUSIC.NS",
    "Waaree Renewab.":      "WAAREERTL.NS",
    "Waaree Renewables":    "WAAREERTL.NS",
    "RRP Defense":          "530929.BO",
    "JD Cables":            "544524.BO",
    "Vivid Electromech":    "VIVIDEL.NS",
    "One Global Serv":      "514330.BO",
    "One Global Services":  "514330.BO",
    "Australian Prem":      "APS.NS",
    "Crizac":               "CRIZAC.NS",
    "Frontier Springs":     "FRONTSP.NS",
    "Shilchar Tech.":       "SHILCTECH.NS",
    "Shilchar Technologies":"SHILCTECH.NS",
    "Jeena Sikho":          "JSLL.NS",
    "Rajesh Power":         "544291.BO",
    "Unified Data":         "544406.BO",
    "Om Power Transmission":"OMPOWER.NS",
    "Garuda Cons":          "GARUDA.NS",
    "Garuda Construction":  "GARUDA.NS",
    "GK Energy":            "GKENERGY.NS",
    "Canara Robeco":        "CRAMC.NS",
    "Dynacons Sys.":        "DSSL.NS",
    "Bondada Engineer":     "543971.BO",
    "Bondada Engineering":  "543971.BO",
    "Oswal Pumps":          "OSWALPUMPS.NS",
    "Prizor Viztech":       "PRIZOR.NS",
    "SRM Contractors":      "SRM.NS",
    "Sathlokhar Sys.":      "SSEGL.NS",
    "Ganesh Green":         "GGBL.NS",
    "Sacheerome":           "SACHEEROME.NS",

    # === SCREEN 3 — SPECIAL SITUATIONS ===
    "The Bombay Burmah":    "BBTC.NS",
    "Bombay Burmah":        "BBTC.NS",
    "Expleo Solutions":     "EXPLEOSOL.NS",
    "Petronet LNG":         "PETRONET.NS",
    "Panama Petrochem":     "PANAMAPET.NS",
    "Siyaram Silk":         "SIYSIL.NS",
    "AGI Greenpac":         "AGI.NS",
    "D B Corp":             "DBCORP.NS",
    "Indraprastha Gas":     "IGL.NS",
    "IGL":                  "IGL.NS",
    "S P I C":              "SPIC.NS",
    "Route Mobile":         "ROUTE.NS",
    "Balmer Law. Inv.":     "BLIL.NS",
    "Balmer Lawrie":        "BLIL.NS",
    "HMA Agro Inds.":       "HMAAGRO.NS",
    "HMA Agro":             "HMAAGRO.NS",
    "Kalyani Steels":       "KSL.NS",
    "Mah. Seamless":        "MAHSEAMLES.NS",
    "Maharashtra Seamless": "MAHSEAMLES.NS",
    "Kama Holdings":        "KAMAHOLD.NS",
    "Monte Carlo Fas.":     "MONTECARLO.NS",
    "Monte Carlo Fashion":  "MONTECARLO.NS",
    "Dollar Industrie":     "DOLLAR.NS",
    "Dollar Industries":    "DOLLAR.NS",
}

# Stocks that are structurally not true compounders — flag for review
STRUCTURAL_CAUTION = {
    "NATIONALUM.NS":  "Cyclical commodity business — ROCE driven by aluminium price cycle, not structural moat",
    "COALINDIA.NS":   "Cash cow but limited growth in energy transition — evaluate as value, not compounder",
    "530929.BO":      "BSE-only, very small, earnings volatile — high speculative risk",
    "514330.BO":      "Profit spike appears one-time (+522% QoQ) — verify sustainability",
    "544406.BO":      "Very small cap, limited information — exercise extreme caution",
    "GGBL.NS":        "Sales spike +300% QoQ — investigate if one-time contract or structural",
}


# -----------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------

def http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; HeritageLedgerBot/1.0)",
        "Accept": "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return ""


def yahoo_search_symbol(company_name: str) -> str | None:
    """Use Yahoo Finance search API to find NSE/BSE symbol for a company name."""
    query = urllib.parse.quote(company_name + " NSE India")
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=5&newsCount=0"
    body = http_get(url)
    if not body:
        return None
    try:
        data = json.loads(body)
        for q in (data.get("quotes") or []):
            sym = q.get("symbol", "")
            exchange = q.get("exchange", "")
            # Prefer NSE, then BSE
            if sym.endswith(".NS") or exchange in ("NSE", "NSI"):
                return sym
        for q in (data.get("quotes") or []):
            sym = q.get("symbol", "")
            if sym.endswith(".BO"):
                return sym
    except Exception:
        pass
    return None


def parse_float(val: str) -> float | None:
    """Safely parse a numeric string from CSV."""
    if not val or val.strip() in ("", "-", "N/A", "NA", "#N/A"):
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def read_csv_screen(filepath: Path) -> list[dict]:
    """Read a Screener.in CSV export. Returns list of raw row dicts."""
    if not filepath.exists():
        print(f"  ! CSV not found: {filepath.name} — skipping")
        return []

    rows = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Name") or "").strip()
            if not name or name == "Name":
                continue
            rows.append(dict(row))

    print(f"  ✓ {filepath.name}: {len(rows)} rows")
    return rows


def normalize_stock(row: dict, tier: str) -> dict:
    """Convert a raw Screener CSV row into our standard stock dict."""
    name = (row.get("Name") or "").strip()

    # Look up Yahoo symbol
    symbol = NAME_TO_SYMBOL.get(name)

    # Derive a clean ticker from the name map or company name
    ticker = symbol.split(".")[0] if symbol else name.upper()[:12].replace(" ", "")

    # Parse all the fundamentals Screener provides
    stock = {
        "name":           name,
        "ticker":         ticker,
        "symbol":         symbol,           # May be None if not in map
        "tier":           tier,
        "sector":         None,             # Screener doesn't export sector in default view
        # Current metrics
        "price":          parse_float(row.get("CMP Rs.")),
        "pe":             parse_float(row.get("P/E")),
        "market_cap_cr":  parse_float(row.get("Mar Cap Rs.Cr.")),
        "div_yield":      parse_float(row.get("Div Yld %")),
        # Profitability
        "net_profit_qtr": parse_float(row.get("NP Qtr Rs.Cr.")),
        "profit_growth_qtr": parse_float(row.get("Qtr Profit Var %")),
        "sales_qtr":      parse_float(row.get("Sales Qtr Rs.Cr.")),
        "sales_growth_qtr": parse_float(row.get("Qtr Sales Var %")),
        # ROCE (varies by screen — some have 5yr, some 3yr)
        "roce":           parse_float(row.get("ROCE %")),
        "roce_5yr":       parse_float(row.get("ROCE 5Yr %")),
        "roce_3yr":       parse_float(row.get("ROCE 3Yr %")),
        "price_to_book":  parse_float(row.get("CMP / BV")),
        # Status flags
        "is_red_flagged": False,            # Set later by cross-reference
        "status":         "CLEAN",
        "caution_note":   STRUCTURAL_CAUTION.get(symbol, None),
        "symbol_resolved": symbol is not None,
    }

    return stock


def build_red_flag_names(screens_dir: Path) -> set[str]:
    """Return set of company names appearing on any Red Flag screen."""
    names = set()
    red_flag_files = [
        screens_dir / "screen_4a_pledging.csv",
        screens_dir / "screen_4b_leverage.csv",
        screens_dir / "screen_4c_declining.csv",
        screens_dir / "screen_4d_promoter.csv",
    ]
    for f in red_flag_files:
        if not f.exists():
            print(f"  ! Red flag CSV missing: {f.name}")
            continue
        with open(f, "r", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                n = (row.get("Name") or "").strip()
                if n and n != "Name":
                    names.add(n)
    print(f"  ✓ Red flag names: {len(names)} stocks to avoid")
    return names


def resolve_missing_symbols(stocks: list[dict]) -> list[dict]:
    """
    For stocks where we couldn't find the Yahoo symbol from our map,
    try Yahoo's search API. Rate-limited — only called for unknowns.
    """
    unresolved = [s for s in stocks if not s["symbol_resolved"]]
    if not unresolved:
        return stocks

    print(f"  → resolving {len(unresolved)} unknown symbols via Yahoo search...")
    for s in unresolved:
        sym = yahoo_search_symbol(s["name"])
        if sym:
            s["symbol"] = sym
            s["ticker"] = sym.split(".")[0]
            s["symbol_resolved"] = True
            print(f"    ✓ {s['name']} → {sym}")
        else:
            print(f"    ! {s['name']} → symbol not found, will skip price fetch")
        time.sleep(0.3)  # polite

    return stocks


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------

def main():
    print(f"\n[{dt.datetime.now().isoformat()}] Heritage Ledger — Data Ingest")
    print(f"  screens dir: {SCREENS_DIR.resolve()}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Build red flag universe
    print("\n--- Red Flags ---")
    red_flag_names = build_red_flag_names(SCREENS_DIR)

    # 2. Read positive screens
    print("\n--- Reading Screens ---")
    raw_compounders     = read_csv_screen(SCREENS_DIR / "screen_1_compounders.csv")
    raw_multibaggers    = read_csv_screen(SCREENS_DIR / "screen_2_multibaggers.csv")
    raw_special         = read_csv_screen(SCREENS_DIR / "screen_3_special_situations.csv")

    # 3. Normalize each stock
    print("\n--- Normalizing ---")
    seen_names = set()
    compounders, multibaggers, special = [], [], []

    for raw in raw_compounders:
        s = normalize_stock(raw, "COMPOUNDER")
        if s["name"] in red_flag_names:
            s["is_red_flagged"] = True
            s["status"] = "AVOID_RED_FLAG"
        seen_names.add(s["name"])
        compounders.append(s)

    for raw in raw_multibaggers:
        s = normalize_stock(raw, "MULTIBAGGER")
        if s["name"] in seen_names:
            continue  # already in compounders, higher tier wins
        if s["name"] in red_flag_names:
            s["is_red_flagged"] = True
            s["status"] = "AVOID_RED_FLAG"
        seen_names.add(s["name"])
        multibaggers.append(s)

    for raw in raw_special:
        s = normalize_stock(raw, "SPECIAL_SITUATION")
        if s["name"] in seen_names:
            continue
        if s["name"] in red_flag_names:
            s["is_red_flagged"] = True
            s["status"] = "AVOID_RED_FLAG"
        seen_names.add(s["name"])
        special.append(s)

    all_stocks = compounders + multibaggers + special

    # 4. Resolve missing symbols
    print("\n--- Resolving Symbols ---")
    all_stocks = resolve_missing_symbols(all_stocks)

    # Re-split back into tiers after symbol resolution
    compounders = [s for s in all_stocks if s["tier"] == "COMPOUNDER"]
    multibaggers = [s for s in all_stocks if s["tier"] == "MULTIBAGGER"]
    special = [s for s in all_stocks if s["tier"] == "SPECIAL_SITUATION"]

    # 5. Stats
    total = len(all_stocks)
    clean = sum(1 for s in all_stocks if not s["is_red_flagged"])
    flagged = total - clean
    unresolved_sym = sum(1 for s in all_stocks if not s["symbol_resolved"])

    print(f"\n--- Summary ---")
    print(f"  Compounders:        {len(compounders):3d}  ({sum(1 for s in compounders if s['is_red_flagged'])} red-flagged)")
    print(f"  Multibaggers:       {len(multibaggers):3d}  ({sum(1 for s in multibaggers if s['is_red_flagged'])} red-flagged)")
    print(f"  Special Situations: {len(special):3d}  ({sum(1 for s in special if s['is_red_flagged'])} red-flagged)")
    print(f"  Total:              {total:3d}  | Clean: {clean} | Flagged: {flagged}")
    print(f"  Unresolved symbols: {unresolved_sym}")

    # 6. Write output
    output = {
        "last_updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(),
        "source": "Screener.in Premium CSV exports",
        "stats": {
            "total": total,
            "clean": clean,
            "flagged": flagged,
            "unresolved_symbols": unresolved_sym,
            "compounders_count": len(compounders),
            "multibaggers_count": len(multibaggers),
            "special_situations_count": len(special),
        },
        "universe": {
            "compounders": compounders,
            "multibaggers": multibaggers,
            "special_situations": special,
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n  ✓ Written: {OUTPUT_FILE}")
    print(f"[done] Data ingest complete.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"  ! Unexpected error: {e}")
        print("  ! Exiting with code 0 to allow workflow to continue")
        import sys
        sys.exit(0)
