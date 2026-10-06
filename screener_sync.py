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

# screen_id AND slug_name — the export endpoint requires both.
# Verified against the live site on 2026-10-06 from /explore/.
SCREEN_MAP = {
    "screen_1_compounders.csv":          ("3695211", "1-compounders"),
    "screen_2_multibaggers.csv":         ("3695216", "2-multibaggers"),
    "screen_3_special_situations.csv":   ("3695219", "3-special-situations"),
    "screen_4a_pledging.csv":            ("3695220", "4a-red-flag-pledging"),
    "screen_4b_leverage.csv":            ("3695223", "4b-red-flag-leverage"),
    "screen_4c_declining.csv":           ("3695224", "4c-red-flag-declining"),
    "screen_4d_promoter.csv":            ("3695226", "4d-red-flag-promoter"),
    "screen_5_early_quality.csv":        ("3696139", "early-quality"),
    "screen_6_emerging_compounders.csv": ("3696145", "emerging-compounders"),
    "screen_7_inflection_watch.csv":     ("3696147", "inflection-watch"),
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
    """Build an opener carrying a pre-existing sessionid cookie.

    The cookie goes into the CookieJar, NOT into a static Cookie header. A
    static header overrides the jar, so the csrftoken cookie Django sets when
    we load the screen page is never sent back — and the export POST is
    rejected with HTTP 403 every time.
    """
    jar = http.cookiejar.CookieJar()
    jar.set_cookie(http.cookiejar.Cookie(
        version=0, name="sessionid", value=session,
        port=None, port_specified=False,
        domain=".screener.in", domain_specified=True, domain_initial_dot=True,
        path="/", path_specified=True,
        secure=True, expires=None, discard=False,
        comment=None, comment_url=None, rest={}, rfc2109=False,
    ))
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar))


def authenticate():
    """Pick an auth mode and return (opener, mode_label)."""
    user = os.environ.get("SCREENER_USERNAME", "").strip()
    pwd = os.environ.get("SCREENER_PASSWORD", "")
    session = os.environ.get("SCREENER_SESSION", "").strip()

    if user and pwd:
        print("  auth mode: credentials (fresh session per run)")
        try:
            return login_with_credentials(user, pwd), "credentials"
        except RuntimeError as e:
            # Do not lose the run over a bad password when a cookie is
            # available. Screener also rejects some datacenter logins, so a
            # credential failure here is not always a wrong password.
            print(f"  ! credential login failed: {e}", file=sys.stderr)
            if session:
                print("  ! falling back to SCREENER_SESSION cookie",
                      file=sys.stderr)
            else:
                raise

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

def download(opener, screen: tuple[str, str], filename: str) -> bool:
    """Export one screen to CSV.

    Screener does NOT serve exports from /screen/<id>/export/ — that path has
    never existed and returned 404 on every run since this script was written.
    The real export is a POST to /api/export/screen/ carrying the screen id,
    the slug, and a CSRF token lifted from the screen page, exactly as the
    site's own Export button does. Verified against the live site 2026-10-06:
    returns text/csv with Content-Disposition attachment.
    """
    screen_id, slug = screen
    page_url = f"{BASE}/screens/{screen_id}/{slug}/"

    # Step 1 — load the screen page to mint a CSRF token for this session.
    try:
        req = urllib.request.Request(page_url, headers={
            "User-Agent": UA, "Accept": "text/html,*/*",
        })
        with opener.open(req, timeout=60) as r:
            html = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ! {filename}: screen page 404 — screen {screen_id}/{slug} "
                  f"does not exist or is not visible to this account")
        else:
            print(f"  ! {filename}: screen page HTTP {e.code}")
        return False
    except Exception as e:
        print(f"  ! {filename}: screen page error: {e}")
        return False

    m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', html)
    if not m:
        print(f"  ! {filename}: no CSRF token on the screen page — "
              f"not logged in, or Screener changed its markup")
        return False
    csrf = m.group(1)

    # Step 2 — POST the export request.
    export_url = (f"{BASE}/api/export/screen/?url_name=screen"
                  f"&screen_id={urllib.parse.quote(screen_id)}"
                  f"&slug_name={urllib.parse.quote(slug)}")
    data = urllib.parse.urlencode({"csrfmiddlewaretoken": csrf}).encode()
    req = urllib.request.Request(export_url, data=data, headers={
        "User-Agent": UA,
        "Referer": page_url,          # Django rejects cross-origin POSTs
        "Origin": BASE,
        "X-CSRFToken": csrf,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/csv,*/*",
    })
    try:
        with opener.open(req, timeout=60) as r:
            content = r.read()
            ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  ! {filename}: HTTP 403 on export — CSRF rejected, or "
                  f"Premium not active on this account")
        elif e.code == 404:
            print(f"  ! {filename}: HTTP 404 on export endpoint")
        else:
            print(f"  ! {filename}: export HTTP {e.code}")
        return False
    except Exception as e:
        print(f"  ! {filename}: export error: {e}")
        return False

    if "csv" not in ctype.lower() and not content[:5] == b"Name,":
        print(f"  ! {filename}: expected CSV, got Content-Type '{ctype}' "
              f"({len(content)}B) — export did not produce a file")
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
    for filename, screen in SCREEN_MAP.items():
        results[filename] = download(opener, screen, filename)
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
