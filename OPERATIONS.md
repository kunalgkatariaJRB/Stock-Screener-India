# Operations Runbook

How the Heritage Ledger pipeline runs, what to do when it breaks, and the
one-time setup needed for it to run unattended.

---

## The weekly cycle

| When | What runs | What happens |
|---|---|---|
| **Wed 06:00 UTC** | `screener_sync.yml` | Logs in to Screener, pulls one screen as a probe. Opens a GitHub issue if access is broken — four days before it would matter. |
| **Sun 02:30 UTC** (08:00 IST) | `refresh.yml` | Logs in, downloads all 10 screen CSVs, builds the universe, runs the Claude analysis, verifies the output, commits and pushes. |
| **Every push / PR** | `ci.yml` | Runs the regression suite on Linux. |

No manual step. You should only hear from this when it breaks.

---

## One-time setup

Add these in **Settings → Secrets and variables → Actions**.

### Required

| Secret | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for the analysis |

### Screener access — pick ONE mode

**Mode A — credentials (recommended, nothing ever expires)**

| Secret | What it is |
|---|---|
| `SCREENER_USERNAME` | Your screener.in login email |
| `SCREENER_PASSWORD` | Your screener.in password |

The sync logs in fresh on every run, so there is nothing to rotate.

> Use a password unique to Screener. It is stored encrypted in GitHub
> Actions secrets and masked in logs, but anyone with write access to this
> repository can arrange to read it. A Screener account is the entire blast
> radius — keep it that way.

**Mode B — session cookie (fallback, expires every 30–45 days)**

| Secret | What it is |
|---|---|
| `SCREENER_SESSION` | The `sessionid` cookie value from a logged-in browser |

To get it: log in to screener.in → DevTools → Application → Cookies →
screener.in → copy `sessionid`.

Note this is **not** meaningfully safer than Mode A: a session cookie is a
full bearer credential for your account. The only difference is that it
expires, which caps the exposure window — at the cost of re-pasting it
roughly monthly.

If both modes are configured, credentials win.

---

## When something breaks

Every failure opens a GitHub issue and turns the Actions run red. The
pipeline leaves `data.json` untouched rather than publishing bad data, and
the dashboard shows a stale-data banner after 8 days.

### "universe has only N stocks — expected 300+"

A screen CSV did not resolve. Check `data/screens/` has exactly one file per
screen and no two files differ only by case or separator. The ingest refuses
to guess between `Screen_1_compounders.csv` and `screen_1_compounders.csv`.

### "tier X had N stocks in but produced ZERO verdicts"

Claude batches failed. Usually truncation — check whether `BATCH_SIZE` was
raised or the verdict schema grew. The guard in
`tests/test_pipeline.py::test_tier_batch_fits_in_token_budget` should catch
this before merge.

### "data.json is Nh old — refresh did not write"

The ledger call failed validation. Check the step log for the `FAILURE:`
lines, which name the exact missing keys.

### "Screener session cookie needs rotating"

Mode B only. Re-paste `SCREENER_SESSION`, or switch to Mode A and stop
having this problem.

### Screener changed its login form

`login_with_credentials` raises "no csrfmiddlewaretoken on the login page".
Fall back to `SCREENER_SESSION` until the login flow is updated.

---

## Running locally

```bash
pip install -r requirements.txt

# Full pipeline
SCREENER_USERNAME=... SCREENER_PASSWORD=... python screener_sync.py
python data_ingest.py
ANTHROPIC_API_KEY=... python refresh.py

# Tests only — no network, no API spend
python tests/test_pipeline.py
```

`data_ingest.py` and `tests/` need no secrets and make no API calls.

---

## Changing the schedule

The cron lives in `.github/workflows/refresh.yml`:

```yaml
- cron: '30 2 * * 0'    # weekly, Sunday 08:00 IST
# - cron: '30 2 * * *'  # daily — roughly 7x the Claude spend
```

The system prompt describes the cadence as weekly. If you move to daily,
update the "weekly run" language in `SYSTEM_PROMPT` in `refresh.py` to match,
or the model will reason about the wrong reassessment window.

---

## Design notes

**Everything fails loudly.** The pipeline previously caught every exception
and exited 0, which meant three months of green ticks over a dead pipeline
and a dashboard serving July verdicts in October. Scripts now exit non-zero,
workflows do not swallow push failures, and the dashboard says so when its
data is old.

**The sync is the single writer** for `data/screens/`. It purges colliding
filename spellings before writing the canonical lowercase name. Do not
upload CSVs manually — if you must, delete what the sync wrote first.

**CI runs on Linux deliberately.** The outage that started 2026-09-18 was a
filename case-sensitivity bug that could not reproduce on macOS. Anything
touching file paths must be exercised on a case-sensitive filesystem before
it reaches a Sunday run.
