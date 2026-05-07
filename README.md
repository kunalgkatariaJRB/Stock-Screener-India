# The Heritage Ledger

A fundamentals-first dashboard for Indian equity decisions, built for the family. Live prices, considered verdicts, automatic daily refresh.

---

## What this is

A single-page dashboard that shows:

- **Live prices** for the Nifty, Sensex, Bank Nifty, currencies, commodities, and a curated list of Indian stocks
- **Verdicts** — Conviction Buys, India Tomorrow (small-caps), High Promise, Hold & Watch, Trim or Avoid — each with stated reasoning, fundamentals, catalysts, and risks
- **A live news ticker** scrolling Indian market headlines from Moneycontrol, Business Standard, ET, and Mint
- **A search bar** to look up any NSE/BSE stock instantly
- **A sector compass, earnings diary, and whisper wire**
- **The principles that govern the ledger** — drawn from Graham, Buffett, Munger, and Naval Ravikant

Everything regenerates automatically every morning at 7:30 AM IST. The verdicts you see are not frozen in May 2026 — they reflect yesterday's market and yesterday's news.

---

## How it works (the architecture in 30 seconds)

```
┌────────────────────────┐
│  index.html (UI)       │  ← what your family sees
│  + reads data.json     │
│  + fetches live prices │
│  + fetches RSS news    │
└────────────────────────┘
            ▲
            │  reads
            │
┌────────────────────────┐
│  data.json (verdicts)  │  ← the editorial brain
└────────────────────────┘
            ▲
            │  rewrites once per day
            │
┌────────────────────────┐
│  refresh.py            │  ← calls Claude with fresh
│  (runs in GitHub       │     market data + news,
│   Actions @ 7:30 IST)  │     gets back fresh JSON
└────────────────────────┘
```

The dashboard is a simple static site — no backend, no database. The only "moving part" is a scheduled GitHub Action that runs once a day, calls Claude with the latest market context, and commits an updated `data.json` back to the repo. Your family always sees fresh thinking; you don't have to do anything.

---

## File overview

| File | What it does |
|---|---|
| `index.html` | The dashboard itself — open this in a browser |
| `data.json` | Verdicts, sectors, earnings, whispers (auto-regenerated daily) |
| `refresh.py` | Python script that calls Claude to regenerate `data.json` |
| `.github/workflows/refresh.yml` | The schedule that runs `refresh.py` automatically |
| `README.md` | This file |

---

## One-time setup (about 30 minutes)

You'll do this once, then never touch it again. Follow each step in order.

### Step 1 — Get an Anthropic API key

1. Go to **https://console.anthropic.com/**
2. Sign up (you can use your Google account)
3. Go to **Settings → API Keys → Create Key**
4. Copy the key (starts with `sk-ant-...`) — you only see it once
5. **Important:** Add a small amount of credit (₹500–₹1000) to start. The daily refresh costs roughly ₹2–₹5 per day on default settings, so this lasts months.

### Step 2 — Create a GitHub repo

1. Go to **https://github.com/** — sign up if you don't have an account
2. Click the **+** in the top right → **New repository**
3. Name it whatever you like (`heritage-ledger` is fine)
4. Make it **Public** (free GitHub Pages requires public repos)
5. Click **Create repository**

### Step 3 — Upload the files

The simplest way:

1. On the empty repo page, click **uploading an existing file**
2. Drag in: `index.html`, `data.json`, `refresh.py`, `README.md`
3. For the workflow file, you'll need to create the folder structure:
   - Click **Add file → Create new file**
   - In the filename box, type: `.github/workflows/refresh.yml`
   - Paste the contents of `refresh.yml`
   - Click **Commit changes**

### Step 4 — Add your API key as a secret

1. In your GitHub repo, go to **Settings** (top tabs)
2. In the left sidebar: **Secrets and variables → Actions**
3. Click **New repository secret**
4. Name: `ANTHROPIC_API_KEY` (exactly this — case matters)
5. Value: paste the key from Step 1 (starts with `sk-ant-...`)
6. Click **Add secret**

### Step 5 — Turn on GitHub Pages (free hosting)

1. Repo **Settings → Pages**
2. Under "Source", select **Deploy from a branch**
3. Branch: **main**, folder: **/ (root)**
4. Click **Save**
5. Wait 1–2 minutes. The page will say: *"Your site is live at https://YOUR-USERNAME.github.io/heritage-ledger/"*
6. Open that URL — you should see the dashboard.

### Step 6 — Test the daily refresh

You don't have to wait until 7:30 AM tomorrow to see it work. Trigger it once manually now:

1. Repo → **Actions** tab
2. Left sidebar: click **Refresh Heritage Ledger**
3. Click **Run workflow** → **Run workflow** (green button)
4. Wait about 60–90 seconds. The job should turn green ✓
5. If it's red, click into it and check the logs — usually it's a missing/wrong API key.

If it ran successfully, `data.json` has just been updated by Claude with today's reasoning. Your dashboard will show the new edition label and refreshed verdicts.

**You're done.** The action will now run every morning at 7:30 AM IST automatically.

---

## Day-to-day use

- **Just open the dashboard URL.** That's it. No login, no maintenance.
- The page auto-refreshes prices every 5 minutes when you have the tab open.
- The news ticker pulls fresh headlines on every page load.
- The verdicts and analysis are regenerated daily by the GitHub Action.

### Bookmark it for the family

Bookmark the `https://YOUR-USERNAME.github.io/heritage-ledger/` URL on the family iPad/phones. That's the entry point.

If you'd prefer a custom domain (e.g. `ledger.yourname.com`), GitHub Pages supports that — there's a one-time DNS setup in repo Settings → Pages → Custom domain.

---

## Cost expectations

- **GitHub** — free (public repos)
- **GitHub Pages hosting** — free
- **GitHub Actions** — free (well within the free monthly minutes for public repos)
- **Anthropic API (Claude)** — roughly ₹2–₹5 per day on the default model (`claude-sonnet-4-6`). About ₹60–₹150 per month.

If you want even cheaper updates, change `HERITAGE_MODEL` in `.github/workflows/refresh.yml` to `claude-haiku-4-5-20251001`. That's roughly 5× cheaper.

If you want deeper reasoning, change it to `claude-opus-4-7`. That's roughly 5× more expensive but the most thoughtful analysis available.

---

## Common questions

**Q. Will my family always see today's verdicts?**
Yes. The Action runs at 7:30 AM IST every day and commits the new `data.json`. By the time markets open at 9:15 AM, the dashboard is fresh. If they open it the next afternoon, they're seeing analysis based on yesterday's close + this morning's news.

**Q. What if the Action fails one day?**
The previous `data.json` stays in place. The dashboard keeps showing yesterday's edition until the next successful run. Failures are rare and usually self-resolve.

**Q. Can I edit the stock list manually?**
Yes — `data.json` is plain text. You can edit it on GitHub directly. But remember: the next daily refresh will rewrite it. If you want a stock to permanently appear in your verdicts, edit `refresh.py` and add it to the system prompt's instructions, OR ask Claude in the prompt to always keep that name.

**Q. What if I want to switch off the automation for a while?**
Repo Settings → Actions → General → Disable Actions. The dashboard keeps working with whatever `data.json` was last committed.

**Q. How do I know what changed today vs. yesterday?**
The `lastUpdated` timestamp at the bottom of the page tells you when verdicts were last regenerated. The git history of `data.json` shows you the exact diff between any two days — useful if you want to see Claude's reasoning evolution.

---

## A word on what this is — and isn't

This dashboard is an analytical tool for a family that takes long-term capital allocation seriously. It is not investment advice. Equity investing carries the risk of permanent capital loss, and small-cap and micro-cap names in particular carry meaningful liquidity, governance, and execution risks.

Always verify any figure on the NSE, BSE, or company filings before acting on it. Always consult a SEBI-registered investment advisor and a qualified chartered accountant who knows your full financial picture before making decisions of consequence.

The verdicts here are reasoning, not recommendations. Read them, weigh them, and decide for yourself. That is the only honest way.

---

*The Heritage Ledger — for the long haul, not the long headline.*
