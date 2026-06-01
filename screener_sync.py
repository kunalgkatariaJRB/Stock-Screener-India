"""
Screener CSV Auto-Sync
Downloads all 10 screen CSVs from Screener.in weekly.
Requires SCREENER_SESSION secret in GitHub Secrets.

To get your session cookie:
1. Log into screener.in in Chrome
2. F12 → Application → Cookies → screener.in
3. Copy value of 'sessionid' cookie
4. Add to GitHub Secrets as SCREENER_SESSION
5. Refresh this every 30-45 days when downloads stop working
"""

import os, time, datetime, urllib.request
from pathlib import Path

SESSION = os.environ.get("SCREENER_SESSION", "")
SCREENS_DIR = Path("data/screens")
SCREENS_DIR.mkdir(parents=True, exist_ok=True)

SCREEN_MAP = {
    "screen_1_compounders.csv":          "3695211",
    "screen_2_multibaggers.csv":         "3695216",
    "screen_3_special_situations.csv":   "3695219",
    "screen_4a_pledging.csv":            "3695220",
    "screen_4b_leverage.csv":            "3695223",
    "screen_4c_declining.csv":           "3695224",
    "screen_4d_promoter.csv":            "3695226",
    "screen_5_early_quality.csv":        "3696139",
    "screen_6_emerging_compounders.csv": "3696145",
    "screen_7_inflection_watch.csv":     "3696147",
}


def download(screen_id, filename):
    if "REPLACE" in screen_id:
        print(f"  ! {filename}: ID not configured")
        return False
    url = f"https://www.screener.in/screen/{screen_id}/export/"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Cookie": f"sessionid={SESSION}",
        "Referer": "https://www.screener.in/screens/",
        "Accept": "text/csv,*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read()
        if len(content) < 200:
            print(f"  ! {filename}: too small — session may have expired")
            return False
        (SCREENS_DIR / filename).write_bytes(content)
        print(f"  ✓ {filename}: {len(content):,} bytes")
        return True
    except Exception as e:
        print(f"  ! {filename}: {e}")
        return False


def main():
    print(f"[{datetime.datetime.utcnow().isoformat()}Z] Screener sync...")
    if not SESSION:
        print("  ✗ SCREENER_SESSION secret not set")
        raise SystemExit(1)
    results = []
    for fn, sid in SCREEN_MAP.items():
        results.append(download(sid, fn))
        time.sleep(2)
    ok = sum(results)
    print(f"\n  Done: {ok}/{len(SCREEN_MAP)}")
    if ok < len(SCREEN_MAP) // 2:
        print("  ⚠ Over half failed — check SCREENER_SESSION in Secrets")


if __name__ == "__main__":
    main()
