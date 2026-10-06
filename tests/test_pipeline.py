"""
Heritage Ledger — pipeline regression tests
===========================================
Pure stdlib, no third-party imports, runs in seconds. Every test here maps to
a bug that actually took this pipeline down and went unnoticed.

Run locally:   python tests/test_pipeline.py
Runs in CI on every push via .github/workflows/ci.yml

History these guard:
  - 2026-09-18  lowercase screen_*.csv deleted; code opened literal lowercase
                names; macOS hid it, Linux CI returned 0 stocks for 3 weeks.
  - 2026-06-01  SYSTEM_PROMPT told the model NOT to emit `earnings` while the
                validator REQUIRED it; every compliant run failed validation.
  - BATCH_SIZE=40 at ~400 tok/verdict needed ~16.5k against a 16k cap; every
    full batch truncated and was silently dropped.
"""

import csv
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / "data" / "screens"
UNIVERSE = ROOT / "data" / "processed" / "master_universe.json"

sys.path.insert(0, str(ROOT))

# The logical screen names data_ingest.py asks for.
EXPECTED_SCREENS = [
    "screen_1_compounders",
    "screen_2_multibaggers",
    "screen_3_special_situations",
    "screen_4a_pledging",
    "screen_4b_leverage",
    "screen_4c_declining",
    "screen_4d_promoter",
    "screen_5_early_quality",
    "screen_6_emerging_compounders",
    "screen_7_inflection_watch",
]

REQUIRED_CSV_COLUMNS = {"Name", "NSE Code", "BSE Code", "Current Price"}


def slug(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


class TestScreenFilesResolve(unittest.TestCase):
    """The 2026-09-18 outage: filenames that differ only by case/separator."""

    def test_every_expected_screen_resolves(self):
        from data_ingest import resolve_screen

        unresolved = [
            name for name in EXPECTED_SCREENS
            if resolve_screen(SCREENS, name) is None
        ]
        self.assertEqual(
            unresolved, [],
            f"screens not resolvable: {unresolved}. "
            f"Present: {sorted(p.name for p in SCREENS.glob('*.csv'))}",
        )

    def test_no_two_files_claim_the_same_screen(self):
        """Two spellings of one screen makes 'which is current' unknowable."""
        seen = {}
        for p in sorted(SCREENS.glob("*.csv")):
            seen.setdefault(slug(p.stem), []).append(p.name)
        collisions = {k: v for k, v in seen.items() if len(v) > 1}
        self.assertEqual(
            collisions, {},
            f"multiple CSVs collide on one screen: {collisions}. "
            "Keep exactly one file per screen.",
        )

    def test_resolution_is_case_and_separator_insensitive(self):
        """Guards the fix itself, independent of what's on disk today."""
        from data_ingest import resolve_screen

        for variant in [
            "Screen_1_compounders",
            "screen-1-compounders",
            "SCREEN_1_COMPOUNDERS",
        ]:
            self.assertIsNotNone(
                resolve_screen(SCREENS, variant),
                f"resolver failed on variant {variant!r}",
            )


class TestScreenContents(unittest.TestCase):
    def test_csvs_are_screener_exports_with_required_columns(self):
        from data_ingest import resolve_screen

        for name in EXPECTED_SCREENS:
            path = resolve_screen(SCREENS, name)
            assert path is not None, f"{name} unresolved"
            with open(path, encoding="utf-8-sig") as f:
                header = set(next(csv.reader(f)))
            missing = REQUIRED_CSV_COLUMNS - header
            self.assertEqual(
                missing, set(),
                f"{path.name} missing columns {missing} — "
                "probably a login page, not a CSV export",
            )

    def test_csvs_have_data_rows(self):
        from data_ingest import resolve_screen

        for name in EXPECTED_SCREENS:
            path = resolve_screen(SCREENS, name)
            assert path is not None, f"{name} unresolved"
            with open(path, encoding="utf-8-sig") as f:
                rows = [r for r in csv.DictReader(f) if (r.get("Name") or "").strip()]
            self.assertGreater(
                len(rows), 0, f"{path.name} has a header but no data rows"
            )


class TestIngestProducesRealUniverse(unittest.TestCase):
    """End-to-end: the ingest must not silently publish an empty universe."""

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.run(
            [sys.executable, "data_ingest.py"],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_ingest_exits_zero(self):
        self.assertEqual(
            self.proc.returncode, 0,
            f"data_ingest.py failed:\nSTDOUT:\n{self.proc.stdout}\n"
            f"STDERR:\n{self.proc.stderr}",
        )

    def test_universe_is_populated(self):
        u = json.loads(UNIVERSE.read_text())
        self.assertGreaterEqual(
            u["stats"]["total"], 50,
            f"universe has {u['stats']['total']} stocks — expected 300+",
        )

    def test_no_tier_is_empty(self):
        u = json.loads(UNIVERSE.read_text())
        empty = [k for k, v in u["universe"].items() if not v]
        self.assertEqual(empty, [], f"empty tiers: {empty}")

    def test_symbols_mostly_resolve(self):
        u = json.loads(UNIVERSE.read_text())
        total = u["stats"]["total"]
        unresolved = u["stats"]["unresolved_symbols"]
        self.assertLess(
            unresolved, total * 0.1,
            f"{unresolved}/{total} symbols unresolved — price fetches will fail",
        )

    def test_red_flag_screening_is_active(self):
        """If the red-flag CSVs silently vanish, pledged stocks reach conviction."""
        u = json.loads(UNIVERSE.read_text())
        self.assertGreater(
            u["stats"]["flagged"], 0,
            "zero stocks flagged — red-flag screens are not being applied",
        )


class TestRefreshConfigIsSelfConsistent(unittest.TestCase):
    """Static checks on refresh.py — no API key, no network, no spend."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "refresh.py").read_text(encoding="utf-8")

    def _const(self, name):
        m = re.search(rf"^{name}\s*=\s*(\d+)", self.src, re.M)
        assert m is not None, f"could not find constant {name}"
        return int(m.group(1))

    def test_tier_batch_fits_in_token_budget(self):
        """BATCH_SIZE x ~400 tok/verdict must leave headroom under the cap."""
        batch = self._const("BATCH_SIZE")
        cap = self._const("MAX_TOKENS_TIER")
        # 400 tok/verdict measured from live data.json verdicts; 1.5x safety.
        needed = batch * 400 * 1.5
        self.assertLess(
            needed, cap,
            f"BATCH_SIZE={batch} needs ~{needed:.0f} output tokens but "
            f"MAX_TOKENS_TIER={cap}. Batches will truncate and be dropped.",
        )

    def test_ledger_fits_in_token_budget(self):
        """The 2026-07-03 freeze: the main ledger call truncated at 32000.

        Proven from the run log:
            ✓ 36104 chars | stop=max_tokens | in=10239 out=32000

        The ledger emits up to 41 stocks (the maxima of the five bucket ranges
        in SYSTEM_PROMPT), each carrying exit_targets, position_size,
        selection_rationale, catalysts, risks and trigger_alert — roughly
        850 output tokens apiece — plus 12 sectors and whispers.
        """
        cap = self._const("MAX_TOKENS_LEDGER")

        # Derive the stock count from the prompt itself so this test tracks
        # the prompt rather than a number copied into the test.
        m = re.search(
            r"conviction \((\d+)-(\d+)\), longBets \((\d+)-(\d+)\), "
            r"highPromise \((\d+)-(\d+)\),\s*watchClose \((\d+)-(\d+)\), "
            r"trimAvoid \((\d+)-(\d+)\)",
            self.src,
        )
        self.assertIsNotNone(
            m, "could not find the bucket size ranges in SYSTEM_PROMPT"
        )
        assert m is not None
        maxima = [int(g) for g in m.groups()[1::2]]
        max_stocks = sum(maxima)

        needed = max_stocks * 850 + 3000   # stocks + sectors/whispers/narrative
        self.assertLess(
            needed, cap,
            f"the ledger can be asked for up to {max_stocks} stocks "
            f"(~{needed} output tokens) but MAX_TOKENS_LEDGER={cap}. "
            "The response will truncate and data.json will silently freeze.",
        )

    def test_ledger_shape_variants_are_normalised(self):
        """The exact payload that failed run 37437454293 must now validate.

        The model returned 'last_updated' and put the five buckets at the top
        level instead of under 'stocks'. Both are fair readings of the old
        prompt, and rejecting one cost a full run and ~42k output tokens.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "refresh_mod", ROOT / "refresh.py")
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        buckets = ["conviction", "longBets", "highPromise",
                   "watchClose", "trimAvoid"]
        actual = {"edition": "x", "last_updated": "t", "macroNarrative": "m",
                  "whispers": [], "sectors": []}
        for b in buckets:
            actual[b] = []

        fixed = mod.normalize_ledger(dict(actual))
        for key in ["edition", "lastUpdated", "macroNarrative",
                    "stocks", "sectors", "whispers"]:
            self.assertIn(key, fixed, f"{key} missing after normalisation")
        for b in buckets:
            self.assertIn(b, fixed["stocks"], f"{b} not moved under stocks")

        # The already-correct shape must survive untouched.
        nested = {"edition": "x", "lastUpdated": "t", "macroNarrative": "m",
                  "sectors": [], "whispers": [],
                  "stocks": {b: [] for b in buckets}}
        again = mod.normalize_ledger(dict(nested))
        self.assertEqual(sorted(again["stocks"]), sorted(buckets))

    def test_prompt_states_the_top_level_shape(self):
        """Leaving the skeleton to inference is what caused the mismatch."""
        self.assertIn("REQUIRED TOP-LEVEL SHAPE", self.src)
        self.assertIn('"lastUpdated"', self.src)

    def test_validator_does_not_require_what_the_prompt_forbids(self):
        """The 2026-06-01 landmine: prompt says omit `earnings`, gate demanded it."""
        m = re.search(r"required_top\s*=\s*\[([^\]]*)\]", self.src)
        assert m is not None, "could not find required_top"
        required = set(re.findall(r'"([^"]+)"', m.group(1)))

        forbidden = set()
        for key in required:
            # e.g. "Do not include earnings in the output JSON"
            if re.search(rf"[Dd]o not include {key}\b", self.src):
                forbidden.add(key)
        self.assertEqual(
            forbidden, set(),
            f"required_top demands {forbidden}, but SYSTEM_PROMPT tells the "
            "model not to emit it. Every compliant response fails validation.",
        )

    def test_failures_cause_nonzero_exit(self):
        """The whole outage was invisible because everything exited 0."""
        self.assertIn(
            "sys.exit(1)", self.src,
            "refresh.py has no non-zero exit path — failures will be silent",
        )

    def test_no_exit_zero_swallow_in_ingest(self):
        src = (ROOT / "data_ingest.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "sys.exit(0)", src,
            "data_ingest.py swallows failures with exit(0) — "
            "broken runs will show as green",
        )

    def test_no_deprecated_utcnow(self):
        for name in ["refresh.py", "data_ingest.py", "screener_sync.py"]:
            src = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn(
                "utcnow()", src,
                f"{name} uses datetime.utcnow(), removed in Python 3.12+",
            )


class TestScreenerSyncAuth(unittest.TestCase):
    """The sync is what removes the manual download step — guard its auth logic."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "screener_sync.py").read_text(encoding="utf-8")

    def _with_env(self, **env):
        """Context manager: run with ONLY the given Screener vars set.

        Must stay open across the call under test — an earlier version
        restored the environment before authenticate() ran, which made the
        test fail for the wrong reason.
        """
        import contextlib
        import importlib
        import os

        keys = ("SCREENER_USERNAME", "SCREENER_PASSWORD", "SCREENER_SESSION")

        @contextlib.contextmanager
        def _ctx():
            saved = {k: os.environ.get(k) for k in keys}
            try:
                for k in keys:
                    os.environ.pop(k, None)
                for k, v in env.items():
                    os.environ[k] = v
                mod = importlib.import_module("screener_sync")
                importlib.reload(mod)
                yield mod
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

        return _ctx()

    def test_no_credentials_exits_nonzero(self):
        with self._with_env() as mod:
            with self.assertRaises(SystemExit) as ctx:
                mod.authenticate()
            self.assertNotEqual(ctx.exception.code, 0)

    def test_session_mode_needs_no_network(self):
        with self._with_env(SCREENER_SESSION="dummy-session-value") as mod:
            opener, mode = mod.authenticate()
            self.assertEqual(mode, "session")
            self.assertIsNotNone(opener)

    def test_credentials_take_precedence_over_cookie(self):
        """If both are set, the non-expiring mode must win."""
        with self._with_env(
            SCREENER_USERNAME="u", SCREENER_PASSWORD="p",
            SCREENER_SESSION="cookie",
        ) as mod:
            called = {}

            def fake_login(username, password):
                called["username"] = username
                return "OPENER"

            setattr(mod, "login_with_credentials", fake_login)
            opener, mode = mod.authenticate()
            self.assertEqual(mode, "credentials")
            self.assertEqual(called.get("username"), "u")

    def test_password_is_never_printed(self):
        """A leaked password in an Actions log is a credential disclosure."""
        for line in self.src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "print(" in stripped or "::warning" in stripped:
                self.assertNotIn(
                    "password", stripped.lower().replace("screener_password", ""),
                    f"possible password in log output: {stripped!r}",
                )

    def test_every_screen_has_an_id(self):
        import importlib
        mod = importlib.import_module("screener_sync")
        importlib.reload(mod)
        for filename, entry in mod.SCREEN_MAP.items():
            self.assertIsInstance(
                entry, tuple,
                f"{filename}: SCREEN_MAP entries must be (screen_id, slug) — "
                "the export endpoint requires the slug as well as the id",
            )
            sid, slug = entry
            self.assertRegex(sid, r"^\d+$", f"{filename} has a non-numeric id")
            self.assertRegex(
                slug, r"^[a-z0-9][a-z0-9-]*$",
                f"{filename} has a malformed slug {slug!r}",
            )
        # The sync must cover exactly the screens the ingest expects.
        synced = {Path(f).stem for f in mod.SCREEN_MAP}
        self.assertEqual(
            synced, set(EXPECTED_SCREENS),
            "screener_sync and data_ingest disagree about which screens exist",
        )

    def test_export_uses_the_real_endpoint(self):
        """Guards the 404 that made this script useless from day one.

        /screen/<id>/export/ has never existed on Screener. The working export
        is a POST to /api/export/screen/ with screen_id, slug_name and a CSRF
        token — verified live on 2026-10-06 returning text/csv.
        """
        self.assertIn(
            "/api/export/screen/", self.src,
            "export must POST to /api/export/screen/",
        )
        self.assertNotRegex(
            self.src, r"/screen/\{?screen_id\}?/export/",
            "the /screen/<id>/export/ path is a 404 — it never existed",
        )
        self.assertIn(
            "csrfmiddlewaretoken", self.src,
            "the export POST requires a CSRF token",
        )

    def test_credential_failure_falls_back_to_cookie(self):
        """A bad password must not lose the run when a cookie is available."""
        with self._with_env(
            SCREENER_USERNAME="u", SCREENER_PASSWORD="wrong",
            SCREENER_SESSION="cookie",
        ) as mod:
            def boom(username, password):
                raise RuntimeError("login failed — credentials rejected")

            setattr(mod, "login_with_credentials", boom)
            opener, mode = mod.authenticate()
            self.assertEqual(mode, "session")

    def test_credential_failure_raises_when_no_cookie(self):
        with self._with_env(
            SCREENER_USERNAME="u", SCREENER_PASSWORD="wrong",
        ) as mod:
            def boom(username, password):
                raise RuntimeError("login failed — credentials rejected")

            setattr(mod, "login_with_credentials", boom)
            with self.assertRaises(RuntimeError):
                mod.authenticate()

    def test_sync_writes_canonical_lowercase_names(self):
        """Prevents re-creating the 2026-09-18 duplicate-spelling trap."""
        import importlib
        mod = importlib.import_module("screener_sync")
        importlib.reload(mod)
        for filename in mod.SCREEN_MAP:
            self.assertEqual(
                filename, filename.lower(),
                f"{filename} is not lowercase — will collide with manual uploads",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
