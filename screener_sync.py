"""
Screener CSV Auto-Sync
======================
Downloads every screen CSV from Screener.in so no CSV is ever handled by hand.

Two authentication modes. The script prefers the first one available:

  A. CREDENTIALS  (recommended — fully unattended, nothing to rotate)
       secrets: SCREENER_USERNAME, SCREENER_PASSWORD
     Logs in each run the way a browser does: GET /login/ for the CSRF token,
     POST the form, keep the issued session cookie for the downloads. The
     session is created fresh every run, so nothing can expire between runs.

  B. SESSION COOKIE  (fallback — expires every 30-45 days)
       secret: SCREENER_SESSION
     Paste the 'sessionid' cookie value. Simpler and exposes no password, but
     you must re-paste it roughly monthly. screener_sync.yml probes it every
     Wednesday and raises an issue before the Sunday refresh breaks.

Set EITHER pair. If both are present, credentials win.

Run locally:
    SCREENER_USERNAME=... SCREENER_PASSWORD=... python screener_sync.py
"""

import datetime
import http.cookiejar
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.screener.in"
LOGIN_URL = f"{BASE}/login/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

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


# ---------------------------------------------------------------------------
# FILENAME HYGIENE
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def purge_collisions(filename: str) -> None:
    """Remove any existing CSV for this screen under a different spelling.

    Screener names exports after the screen title, and manual uploads arrive
    with inconsistent case and separators ('Screen_3_special-situations.csv').
    Two files for one screen makes 'which is current' unknowable, so this sync
    is the single writer: it deletes every variant before writing the
    canonical lowercase name.
    """
    target = _slug(Path(filename).stem)
    for p in sorted(SCREENS_DIR.glob("*.csv")):
        if p.name != filename and _slug(p.stem) == target:
            print(f"    - removing stale variant: {p.name}")
            p.unlink()


# ---------------------------------------------------------------------------
# AUTHENTICATION
# ---------------------------------------------------------------------------

def build_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def login_with_credentials(username: str, password: str):
    """Log in as a browser would and return an opener holding the session.

    Screener runs Django's standard auth: a csrfmiddlewaretoken hidden field
    plus username/password, with no CAPTCHA and no second factor. The password
    is read from the environment and never logged.
    """
    opener = build_opener()

    # 1. GET the login page for the CSRF token (and the csrftoken cookie).
    req = urllib.request.Request(LOGIN_URL, headers={"User-Agent": UA})
    with opener.open(req, timeout=30) as r:
        html = r.read().decode("utf-8", errors="replace")

    m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', html)
    if not m:
        raise RuntimeError(
            "no csrfmiddlewaretoken on the login page — Screener changed its "
            "login form; switch to SCREENER_SESSION until this is updated"
        )
    csrf = m.group(1)

    # 2. POST the credentials.
    data = urllib.parse.urlencode({
        "csrfmiddlewaretoken": csrf,
        "username": username,
        "password": password,
        "next": "/dash/",
    }).encode()
    req = urllib.request.Request(LOGIN_URL, data=data, headers={
        "User-Agent": UA,
        "Referer": LOGIN_URL,
        "Origin": BASE,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with opener.open(req, timeout=30) as r:
            body = r.read().decode("utf-8", errors="replace")
            final_url = r.geturl()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"login POST returned HTTP {e.code}") from None

    # 3. Confirm. A failed Django login re-renders the form with an error.
    if "csrfmiddlewaretoken" in body and "/login" in final_url:
        hint = ""
        if re.search(r"correct username and password|Please enter a correct",
                     body, re.I):
            hint = " — credentials rejected"
        raise RuntimeError(f"login failed{hint} (landed back on {final_url})")

    print(f"  ✓ logged in as {username} (session established)")
    return opener


def opener_from_session(session: str):
    """Build an opener that presents a pre-existing sessionid cookie."""
    opener = build_opener()
    opener.addheaders = [
        ("User-Agent", UA),
        ("Cookie", f"sessionid={session}"),
    ]
    return opener


def authenticate():
    """Pick an auth mode and return (opener, mode_label)."""
    user = os.environ.get("SCREENER_USERNAME", "").strip()
    pwd = os.environ.get("SCREENER_PASSWORD", "")
    session = os.environ.get("SCREENER_SESSION", "").strip()

    if user and pwd:
        print("  auth mode: credentials (fresh session per run)")
        return login_with_credentials(user, pwd), "credentials"

    if session:
        print("  auth mode: session cookie (expires every 30-45 days)")
        return opener_from_session(session), "session"

    print(
        "  \u2717 No Screener credentials configured.\n"
        "    Set EITHER:\n"
        "      SCREENER_USERNAME + SCREENER_PASSWORD   (recommended, "
        "nothing to rotate)\n"
        "      SCREENER_SESSION                        (cookie, re-paste "
        "monthly)\n"
        "    in Settings \u2192 Secrets and variables \u2192 Actions.",
        file=sys.stderr,
    )
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# DOWNLOAD
# ---------------------------------------------------------------------------

def download(opener, screen_id: str, filename: str) -> bool:
    url = f"{BASE}/screen/{screen_id}/export/"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": f"{BASE}/screens/",
        "Accept": "text/csv,*/*",
    })
    try:
        with opener.open(req, timeout=60) as r:
            content = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ! {filename}: HTTP 404 — screen {screen_id} not visible "
                  f"to this account (wrong ID, or not your screen)")
        elif e.code in (401, 403):
            print(f"  ! {filename}: HTTP {e.code} — not authenticated")
        else:
            print(f"  ! {filename}: HTTP {e.code}")
        return False
    except Exception as e:
        print(f"  ! {filename}: {e}")
        return False

    if len(content) < 200:
        print(f"  ! {filename}: only {len(content)}B — not a real export")
        return False

    header = content[:400].decode("utf-8", errors="replace").split("\n")[0]
    if "Name" not in header:
        print(f"  ! {filename}: no 'Name' column in header — got an HTML page, "
              f"not a CSV. Session is not valid.")
        return False

    purge_collisions(filename)
    (SCREENS_DIR / filename).write_bytes(content)
    rows = content.count(b"\n") - 1
    print(f"  ✓ {filename}: {len(content):,} bytes, ~{rows} rows")
    return True


def main() -> None:
    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] "
          f"Screener sync...")

    try:
        opener, mode = authenticate()
    except RuntimeError as e:
        print(f"\n  \u2717 AUTHENTICATION FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    results = {}
    for filename, screen_id in SCREEN_MAP.items():
        results[filename] = download(opener, screen_id, filename)
        time.sleep(2)   # be a polite client

    ok = sum(results.values())
    print(f"\n  Done: {ok}/{len(SCREEN_MAP)}")

    if ok < len(SCREEN_MAP):
        failed = [f for f, r in results.items() if not r]
        print(f"\n  \u2717 SYNC FAILED — {len(failed)} screen(s) did not "
              f"download: {failed}", file=sys.stderr)
        if mode == "session":
            print("  \u2717 Most likely the session cookie expired. Re-paste "
                  "SCREENER_SESSION, or switch to SCREENER_USERNAME + "
                  "SCREENER_PASSWORD so nothing needs rotating.",
                  file=sys.stderr)
        else:
            print("  \u2717 Credentials worked but some screens did not "
                  "export — check the screen IDs in SCREEN_MAP and that "
                  "Premium is active.", file=sys.stderr)
        sys.exit(1)

    print("  All screens synced — no manual download needed.")


if __name__ == "__main__":
    main()
