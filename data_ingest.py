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
import sys
from pathlib import Path

# -----------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------

SCREENS_DIR = Path("data/screens")
PROCESSED_DIR = Path("data/processed")
OUTPUT_FILE = PROCESSED_DIR / "master_universe.json"

COLUMN_MAP = {
    'Current Price':                      'price',
    'Price to Earning':                   'pe',
    'Market Capitalization':              'market_cap_cr',
    'Dividend yield':                     'div_yield',
    'Net Profit latest quarter':          'net_profit_qtr',
    'YOY Quarterly profit growth':        'profit_growth_qtr',
    'Sales latest quarter':               'sales_qtr',
    'YOY Quarterly sales growth':         'sales_growth_qtr',
    'Return on capital employed':         'roce',
    'Average return on capital employed 5Years': 'roce_5yr',
    'Sales growth':                       'sales_growth',
    'Profit growth':                      'profit_growth',
    'Operating profit growth':            'op_profit_growth',
    'EPS':                                'eps_ttm',
    'EPS latest quarter':                 'eps_latest_qtr',
    'EPS growth 3Years':                  'eps_growth_3yr',
    'TTM Result Date':                    'ttm_result_date',
    'Industry':                           'industry',
    'Industry Group':                     'industry_group',
    'NSE Code':                           'nse_code',
    'BSE Code':                           'bse_code',
    'ISIN Code':                          'isin_code',
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

    # Use NSE Code directly from Screener — far more reliable than name lookup
    nse_code = str(row.get('NSE Code', '') or '').strip()
    bse_code = str(row.get('BSE Code', '') or '').strip()
    if bse_code and bse_code not in ('nan', '0', ''):
        try:
            bse_code = str(int(float(bse_code))).zfill(6)
        except (ValueError, TypeError):
            pass

    if nse_code and nse_code not in ('nan', '0', ''):
        symbol = nse_code + '.NS'
        ticker = nse_code
        symbol_resolved = True
    elif bse_code and bse_code not in ('nan', '0', ''):
        symbol = bse_code + '.BO'
        ticker = bse_code
        symbol_resolved = True
    else:
        symbol = None
        ticker = name.upper()[:12].replace(' ', '')
        symbol_resolved = False

    stock = {
        "name":           name,
        "ticker":         ticker,
        "symbol":         symbol,
        "tier":           tier,
        "sector":         row.get('Industry', None) or row.get('Industry Group', None),
        # Current metrics
        "price":          parse_float(row.get("Current Price")),
        "pe":             parse_float(row.get("Price to Earning")),
        "market_cap_cr":  parse_float(row.get("Market Capitalization")),
        "div_yield":      parse_float(row.get("Dividend yield")),
        # Profitability
        "net_profit_qtr":    parse_float(row.get("Net Profit latest quarter")),
        "profit_growth_qtr": parse_float(row.get("YOY Quarterly profit growth")),
        "sales_qtr":         parse_float(row.get("Sales latest quarter")),
        "sales_growth_qtr":  parse_float(row.get("YOY Quarterly sales growth")),
        # ROCE
        "roce":           parse_float(row.get("Return on capital employed")),
        "roce_5yr":       parse_float(row.get("Average return on capital employed 5Years")),
        # EPS
        "eps_ttm":        parse_float(row.get("EPS")),
        "eps_latest_qtr": parse_float(row.get("EPS latest quarter")),
        "eps_growth_3yr": parse_float(row.get("EPS growth 3Years")),
        "ttm_result_date": row.get("TTM Result Date", None),
        # Growth
        "sales_growth":      parse_float(row.get("Sales growth")),
        "profit_growth":     parse_float(row.get("Profit growth")),
        "op_profit_growth":  parse_float(row.get("Operating profit growth")),
        # Status flags
        "is_red_flagged":  False,
        "status":          "CLEAN",
        "caution_note":    None,
        "symbol_resolved": symbol_resolved,
    }

    # Fix B — TTM staleness flag
    stale = False
    if stock.get('ttm_result_date'):
        try:
            import datetime as _dt
            date_str = str(int(float(str(stock['ttm_result_date'])))).zfill(6)
            year, month = int(date_str[:4]), int(date_str[4:6])
            result_date = _dt.date(year, month, 1)
            stale = (_dt.date.today() - result_date).days > 180
        except Exception:
            pass
    stock['data_stale'] = stale

    # Fix C — EPS deterioration flag
    eps_det = False
    if stock.get('eps_ttm') and stock.get('eps_latest_qtr'):
        try:
            if float(stock['eps_latest_qtr']) < (float(stock['eps_ttm']) / 4) * 0.7:
                eps_det = True
        except Exception:
            pass
    stock['eps_deteriorating'] = eps_det

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
    raw_compounders      = read_csv_screen(SCREENS_DIR / "screen_1_compounders.csv")
    raw_multibaggers     = read_csv_screen(SCREENS_DIR / "screen_2_multibaggers.csv")
    raw_special          = read_csv_screen(SCREENS_DIR / "screen_3_special_situations.csv")
    raw_early_quality    = read_csv_screen(SCREENS_DIR / "screen_5_early_quality.csv")
    raw_emerging         = read_csv_screen(SCREENS_DIR / "screen_6_emerging_compounders.csv")
    raw_inflection       = read_csv_screen(SCREENS_DIR / "screen_7_inflection_watch.csv")

    # 3. Normalize each stock
    print("\n--- Normalizing ---")
    seen_names = set()
    compounders, multibaggers, special = [], [], []
    early_quality, emerging, inflection = [], [], []

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
            continue
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

    for raw in raw_early_quality:
        s = normalize_stock(raw, "EARLY_QUALITY")
        if s["name"] in seen_names:
            continue
        if s["name"] in red_flag_names:
            s["is_red_flagged"] = True
            s["status"] = "AVOID_RED_FLAG"
        seen_names.add(s["name"])
        early_quality.append(s)

    for raw in raw_emerging:
        s = normalize_stock(raw, "EMERGING_COMPOUNDER")
        if s["name"] in seen_names:
            continue
        if s["name"] in red_flag_names:
            s["is_red_flagged"] = True
            s["status"] = "AVOID_RED_FLAG"
        seen_names.add(s["name"])
        emerging.append(s)

    for raw in raw_inflection:
        s = normalize_stock(raw, "INFLECTION")
        if s["name"] in seen_names:
            continue
        if s["name"] in red_flag_names:
            s["is_red_flagged"] = True
            s["status"] = "AVOID_RED_FLAG"
        seen_names.add(s["name"])
        inflection.append(s)

    all_stocks = compounders + multibaggers + special + early_quality + emerging + inflection

    # Re-split back into tiers
    compounders   = [s for s in all_stocks if s["tier"] == "COMPOUNDER"]
    multibaggers  = [s for s in all_stocks if s["tier"] == "MULTIBAGGER"]
    special       = [s for s in all_stocks if s["tier"] == "SPECIAL_SITUATION"]
    early_quality = [s for s in all_stocks if s["tier"] == "EARLY_QUALITY"]
    emerging      = [s for s in all_stocks if s["tier"] == "EMERGING_COMPOUNDER"]
    inflection    = [s for s in all_stocks if s["tier"] == "INFLECTION"]

    # 5. Stats
    total = len(all_stocks)
    clean = sum(1 for s in all_stocks if not s["is_red_flagged"])
    flagged = total - clean
    unresolved_sym = sum(1 for s in all_stocks if not s["symbol_resolved"])

    print(f"\n--- Summary ---")
    print(f"  Compounders:           {len(compounders):3d}")
    print(f"  Multibaggers:          {len(multibaggers):3d}")
    print(f"  Special Situations:    {len(special):3d}")
    print(f"  Early Quality:         {len(early_quality):3d}")
    print(f"  Emerging Compounders:  {len(emerging):3d}")
    print(f"  Inflection Watch:      {len(inflection):3d}")
    print(f"  Total:                 {total:3d} | Clean: {clean} | Flagged: {flagged}")
    print(f"  Unresolved symbols:    {unresolved_sym}")

    # 6. Write output
    output = {
        "last_updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(),
        "source": "Screener.in Premium CSV exports",
        "stats": {
            "total": total,
            "clean": clean,
            "flagged": flagged,
            "unresolved_symbols": unresolved_sym,
            "compounders_count":          len(compounders),
            "multibaggers_count":         len(multibaggers),
            "special_situations_count":   len(special),
            "early_quality_count":        len(early_quality),
            "emerging_compounders_count": len(emerging),
            "inflection_count":           len(inflection),
        },
        "universe": {
            "compounders":          compounders,
            "multibaggers":         multibaggers,
            "special_situations":   special,
            "early_quality":        early_quality,
            "emerging_compounders": emerging,
            "inflection_watch":     inflection,
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
