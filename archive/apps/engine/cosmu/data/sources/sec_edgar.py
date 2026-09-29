# intent: SEC EDGAR Form 4 NET INSIDER-BUY PRESSURE as a per-equity-ticker, point-in-time, LOW-CONFIDENCE
# numeric DataSource. Wires the previously-DISABLED feature_registry entry name="insider_buy_ratio",
# source="sec_edgar". Open-market insider PURCHASES (Form 4 transaction code "P") are a causally-plausible
# bullish tell; open-market SALES ("S") the opposite. The trailing-window net buy ratio is a classic (weak,
# noisy) equity signal — NOT a non-causal control. It must earn its place out-of-sample (the Gate falsifies it).
#
# PIT CONTRACT (critical — the cleanest PIT story in the codebase; read before touching):
#   Each Form 4 filing's available_at = its EDGAR acceptanceDateTime — the instant EDGAR ACCEPTED the filing
#     (the moment it became public). This is a clean PIT marker: there is NO look-ahead, because a transaction
#     dated days earlier is only KNOWABLE to the market once the filing is accepted.
#   query(scope=ticker, as_of) aggregates ONLY filings whose acceptanceDateTime <= as_of, within a trailing
#     window (default 90 days) ending at as_of. The window aggregate's available_at = the LATEST
#     acceptanceDateTime among the filings actually used. A filing accepted AFTER as_of is EXCLUDED.
#   net_buy_ratio = (buy_shares - sell_shares) / (buy_shares + sell_shares)  in [-1, +1].
#   gaps           = None, NOT 0. A ticker not tracked, or no in-window filings, yields value=None.
#   ERROR vs EMPTY (data-honesty split): a live network/parse FAILURE is NOT an observation — the live fetch
#     returns a None sentinel (NOT [] or a partial list), so the query yields value=None. Only a SUCCESSFUL
#     fetch of a tracked issuer with genuinely no open-market P/S filings is a real empty reading (→ None via
#     net_buy_ratio). This keeps a dead/timed-out source from fabricating a false "zero insider activity" 0.
#
# COVERAGE / CONFIDENCE HONESTY (FLAGGED):
#   * Curated seed map of ~10 liquid US large-caps → real zero-padded 10-digit SEC CIKs. Extensible; a ticker
#     not in the map yields value=None (never 0).
#   * Only OPEN-MARKET transactions are counted: code "P" = buy, "S" = sell. Grants/awards ("A"), option
#     exercises ("M"), gifts, etc. are IGNORED (they are not a market-timing signal and are noisy).
#   * Insider trading is a WEAK, NOISY signal (clustering, 10b5-1 plans, size heterogeneity). confidence=0.30,
#     low_confidence True, tier1 in the feature registry. The Gate MUST falsify it via out-of-sample.
#   * No revision policy assumed beyond additions: a filing once accepted is immutable; later filings only add.
#
# OFFLINE / CI:
#   `offline=True` (the default for tests) → bundled deterministic per-ticker transaction fixtures, no HTTP.
#   The fixtures deliberately include: a buy-heavy ticker (ratio > 0), a sell-heavy ticker (ratio < 0), a ticker
#   whose only in-window filing is accepted AFTER the test's as_of (must be EXCLUDED → proves PIT), and a
#   no-data ticker (=> None).

from __future__ import annotations

import json
import ssl
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from cosmu.data.sources.registry import SourceFeature, SourceKind

# Pinned, versioned transform — bump whenever the aggregation logic changes so a gate-passed survivor stays
# byte-for-byte re-runnable.
TRANSFORM_VERSION = "sec-edgar-insider-v1"

# Default trailing window (days) for the net-buy-ratio aggregate, ending at as_of.
_DEFAULT_WINDOW_DAYS = 90

# SEC requires a descriptive User-Agent on every request (see https://www.sec.gov/os/accessing-edgar-data).
_USER_AGENT = "cosmu-engine research github.com/monounsaturated/cosmu"

# Curated EXTENSIBLE seed: liquid US large-caps → their REAL zero-padded 10-digit SEC CIK. A ticker NOT in
# this map yields value=None (a gap, never a fabricated 0). Add tickers here to widen coverage.
_CIK_BY_TICKER: dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "AMZN": "0001018724",
    "TSLA": "0001318605",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "JPM": "0000019617",
    "XOM": "0000034088",
    "WMT": "0000104169",
}

# Deterministic offline fixtures: per-ticker lists of parsed Form 4 transactions. Each transaction is
# {"accepted": datetime (acceptanceDateTime, UTC), "code": "P"|"S", "shares": float}.
# Anchored so the tests (as_of = 2024-04-01) can prove every invariant:
#   AAPL  — buy-heavy   (ratio > 0): all in-window P, one tiny S.
#   XOM   — sell-heavy  (ratio < 0): all in-window S, one tiny P.
#   TSLA  — its ONLY in-window filing is accepted AFTER the test's as_of (2024-04-15) → EXCLUDED → None.
#   WMT   — present in the CIK map but NO transactions at all → None (gap, not 0).
_FIXTURE_TRANSACTIONS: dict[str, list[dict]] = {
    "AAPL": [
        {"accepted": datetime(2024, 2, 10, 14, 30, tzinfo=UTC), "code": "P", "shares": 8_000.0},
        {"accepted": datetime(2024, 3, 5, 9, 15, tzinfo=UTC), "code": "P", "shares": 6_000.0},
        {"accepted": datetime(2024, 3, 20, 16, 0, tzinfo=UTC), "code": "S", "shares": 1_000.0},
        # an OLD buy outside the 90d window ending 2024-04-01 (accepted 2023-11-01) — must be excluded
        {"accepted": datetime(2023, 11, 1, 12, 0, tzinfo=UTC), "code": "P", "shares": 50_000.0},
    ],
    "XOM": [
        {"accepted": datetime(2024, 2, 1, 11, 0, tzinfo=UTC), "code": "S", "shares": 7_000.0},
        {"accepted": datetime(2024, 3, 12, 13, 45, tzinfo=UTC), "code": "S", "shares": 5_000.0},
        {"accepted": datetime(2024, 3, 25, 10, 30, tzinfo=UTC), "code": "P", "shares": 2_000.0},
    ],
    "TSLA": [
        # the ONLY filing — accepted AFTER as_of=2024-04-01 → must be EXCLUDED (proves PIT) → None
        {"accepted": datetime(2024, 4, 15, 15, 0, tzinfo=UTC), "code": "P", "shares": 12_000.0},
    ],
    "WMT": [],  # no transactions → None (gap, never 0)
}


def _ssl_context() -> ssl.SSLContext:
    """certifi-backed TLS context; falls back to the system store if certifi is absent."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def net_buy_ratio(transactions: list[dict], *, as_of: datetime, window_days: int = _DEFAULT_WINDOW_DAYS) -> float | None:
    """PURE, TESTABLE core: net open-market buy pressure over the trailing `window_days` ending at `as_of`.

    Each transaction is {"accepted": datetime, "code": "P"|"S", "shares": float}. ONLY open-market buys (P)
    and sales (S) accepted in (as_of - window_days, as_of] are counted; every other code is ignored.

        net_buy_ratio = (buy_shares - sell_shares) / (buy_shares + sell_shares)   in [-1, +1]

    Returns None (a gap — NEVER 0) when there is no P/S volume in the window. The boundary is PIT-honest:
    a filing accepted AFTER `as_of` is excluded (no look-ahead); a filing older than the window is excluded.
    """
    window_start = as_of - timedelta(days=window_days)
    buy_shares = 0.0
    sell_shares = 0.0
    for t in transactions:
        accepted = t.get("accepted")
        if accepted is None or accepted > as_of or accepted <= window_start:
            continue  # future filing (look-ahead) or older than the window → excluded
        code = t.get("code")
        try:
            shares = float(t.get("shares") or 0.0)
        except (TypeError, ValueError):
            continue
        if shares <= 0.0:
            continue
        if code == "P":
            buy_shares += shares
        elif code == "S":
            sell_shares += shares
        # all other codes (A grants, M option exercise, G gifts, …) ignored — not a market-timing signal
    total = buy_shares + sell_shares
    if total <= 0.0:
        return None  # no open-market P/S volume in the window → gap (None), not 0
    return (buy_shares - sell_shares) / total


def _latest_used_available_at(
    transactions: list[dict], *, as_of: datetime, window_days: int = _DEFAULT_WINDOW_DAYS
) -> datetime | None:
    """available_at for the window aggregate = the LATEST acceptanceDateTime among the P/S filings actually
    used (in-window, accepted <= as_of). None when no filing is used (matches net_buy_ratio's None)."""
    window_start = as_of - timedelta(days=window_days)
    latest: datetime | None = None
    for t in transactions:
        accepted = t.get("accepted")
        if accepted is None or accepted > as_of or accepted <= window_start:
            continue
        if t.get("code") not in ("P", "S"):
            continue
        try:
            if float(t.get("shares") or 0.0) <= 0.0:
                continue
        except (TypeError, ValueError):
            continue
        if latest is None or accepted > latest:
            latest = accepted
    return latest


def _fetch_form4_transactions(cik: str, *, timeout: float) -> list[dict] | None:
    """LIVE path: fetch a ticker's recent Form 4 transactions from SEC EDGAR. Free, NO API KEY — only the
    required descriptive User-Agent.

    PIT HONESTY — the ERROR path is split from the EMPTY-DATA path (a gap must be None, NEVER a real 0):
      * Returns a parsed list [{"accepted": datetime, "code": "P"|"S", "shares": float}, ...] on a SUCCESSFUL
        fetch. The list MAY legitimately be empty ([]) — the issuer simply had no open-market P/S filings —
        which the caller renders as a genuine no-activity gap (None) via net_buy_ratio.
      * Returns None (a FETCH-FAILURE sentinel) on ANY network/parse failure: a dead source, a non-dict
        submissions index, or an exception mid-stream. This is the data-honesty fix: a failed (or PARTIALLY
        completed) fetch must NOT be treated as data. If we returned a truncated/empty list here, a network
        error would be INDISTINGUISHABLE from a real "zero insider activity" reading — fabricating a false
        signal from incomplete data (e.g. a mid-stream failure that already collected only the SELLS would
        manufacture a spurious bearish ratio). None tells the caller "no observation", not "a real 0".

    One dead source still never crashes a query: the caller maps None → a None-valued SourceFeature.

    Strategy: GET the submissions index for the issuer CIK, filter form=="4", then for each recent Form 4
    fetch its RAW ownership XML (the bare primaryDocument filename, with EDGAR's xsl HTML-rendering directory
    prefix stripped — see the fix below) and parse transactionCode (P/S) + transactionShares.
    """
    out: list[dict] = []
    try:
        submissions = _get_json(
            f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=timeout
        )
        if not isinstance(submissions, dict):
            return None  # index unreachable / malformed → FETCH FAILURE (no observation), not an empty 0
        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        accession_numbers = recent.get("accessionNumber") or []
        acceptance = recent.get("acceptanceDateTime") or []
        primary_docs = recent.get("primaryDocument") or []
        cik_int = str(int(cik))  # un-padded CIK for the Archives path
        for i, form in enumerate(forms):
            # NOTE (PIT tradeoff — amendments deliberately EXCLUDED): we count only form=="4", NOT "4/A"
            # (Form 4 AMENDMENTS). A 4/A corrects or restates an earlier Form 4 (a fixed share count, code,
            # or date). Including the amendment WITHOUT removing the superseded original would DOUBLE-COUNT
            # the corrected transaction; honoring an amendment correctly needs accession-level reconciliation
            # we do not yet do. Excluding 4/A keeps each transaction counted once and PIT-clean (a 4/A's own
            # acceptanceDateTime is later than the original, so it cannot leak look-ahead), at the cost of
            # using the as-originally-filed figures rather than the corrected ones. Amendments are a small
            # minority of Form 4s and corrections are usually minor, so the net signal impact is low; revisit
            # with original-supersession logic if coverage widens.
            if form != "4":
                continue
            try:
                accepted = _parse_acceptance(acceptance[i])
                accession = accession_numbers[i].replace("-", "")
                primary = primary_docs[i]
            except (IndexError, AttributeError, ValueError):
                continue
            if accepted is None or not primary or not primary.lower().endswith(".xml"):
                continue
            # LIVE-PATH BUG FIX: for Form 4, EDGAR's primaryDocument is the XSL-TRANSFORMED HTML RENDERING
            # path, e.g. "xslF345X06/form4.xml" — that document contains NO structured
            # nonDerivativeTransaction/transactionCode/transactionShares nodes, so _parse_ownership_doc would
            # parse 0 transactions on EVERY live filing (and insider_buy_ratio would always be None in prod).
            # The RAW structured XML is the SAME filename WITHOUT the xsl directory prefix, e.g.
            #   https://www.sec.gov/Archives/edgar/data/320193/000114036126025622/form4.xml
            # so we strip the leading path segment(s) and fetch only the bare filename. split()[-1] is a no-op
            # for an already-bare primaryDocument (idempotent), so non-xsl forms are unaffected.
            doc_name = primary.split("/")[-1]
            doc_url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{doc_name}"
            )
            for code, shares in _parse_ownership_doc(doc_url, timeout=timeout):
                out.append({"accepted": accepted, "code": code, "shares": shares})
    except Exception:  # noqa: BLE001 — best-effort OSINT; a mid-stream failure is NO OBSERVATION, never a 0
        # Discard any partially-collected `out`: a truncated list would fabricate a wrong ratio. The whole
        # fetch failed → None (a gap the caller surfaces as a None value), not a fabricated empty/partial 0.
        return None
    return out


def _get_json(url: str, *, timeout: float) -> object | None:
    """GET a JSON document with the SEC-required descriptive User-Agent. None on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — best-effort OSINT; degrade gracefully
        return None


def _parse_acceptance(raw: str) -> datetime | None:
    """Parse an EDGAR acceptanceDateTime ('YYYY-MM-DDTHH:MM:SS.000Z' or similar) into a UTC datetime."""
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _parse_ownership_doc(doc_url: str, *, timeout: float) -> list[tuple[str, float]]:
    """Fetch + parse one Form 4 ownership primary_doc.xml. Returns (transactionCode, transactionShares)
    pairs for OPEN-MARKET P/S non-derivative transactions only. [] on any failure."""
    import xml.etree.ElementTree as ET  # stdlib; deferred import (only used on the live path)

    req = urllib.request.Request(doc_url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            root = ET.fromstring(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — best-effort OSINT; degrade gracefully
        return []
    pairs: list[tuple[str, float]] = []
    try:
        for txn in root.iter("nonDerivativeTransaction"):
            code_el = txn.find("./transactionCoding/transactionCode")
            shares_el = txn.find("./transactionAmounts/transactionShares/value")
            if code_el is None or shares_el is None:
                continue
            code = (code_el.text or "").strip()
            if code not in ("P", "S"):
                continue
            try:
                shares = float((shares_el.text or "").strip())
            except (TypeError, ValueError):
                continue
            if shares > 0.0:
                pairs.append((code, shares))
    except Exception:  # noqa: BLE001 — malformed doc → honest empty
        return pairs
    return pairs


@dataclass
class SecEdgarInsiderSource:
    """SEC EDGAR Form 4 net insider-buy pressure as a named, per-equity-ticker, point-in-time DataSource.

    Each observation answers: "over the trailing window ending at `as_of`, was open-market insider activity
    net-buying (ratio > 0) or net-selling (ratio < 0) for this ticker?" Only filings whose EDGAR
    acceptanceDateTime <= as_of are used — the cleanest PIT marker available (a filing is only knowable once
    accepted). A ticker not in the curated CIK map, or with no in-window open-market P/S filings, yields None
    (a gap, NEVER 0).

    Confidence 0.30 (low): insider trading is a weak, noisy signal; must earn its place via OOS (the Gate
    falsifies it). tier1 in the feature registry; low_confidence True always.
    """

    name: str = "insider_buy_ratio"
    kind: SourceKind = "osint"
    metric: str = "insider_buy_ratio"
    prior: str = (
        "Net open-market insider-buy pressure from SEC Form 4 filings: "
        "(buy_shares - sell_shares) / (buy_shares + sell_shares) over a trailing 90-day window, counting "
        "ONLY open-market purchases (code P, bullish) and sales (code S, bearish); grants/exercises ignored. "
        "Insiders plausibly time their own open-market trades on private conviction — a causally-plausible, "
        "but WEAK and NOISY, bullish/bearish tell (NOT a non-causal control). available_at = each filing's "
        "EDGAR acceptanceDateTime; only filings accepted <= as_of are used (no look-ahead). Gaps are None "
        "(not 0). LOW-CONFIDENCE — must earn its place out-of-sample; the Gate falsifies it."
    )
    transform_version: str = TRANSFORM_VERSION
    confidence: float = 0.30  # low — weak, noisy equity signal; the Gate must falsify it
    window_days: int = _DEFAULT_WINDOW_DAYS
    offline: bool = False
    timeout: float = 20.0
    # inject a fixture {ticker: [transactions]} for tests; None = use the bundled default
    _fixture: dict[str, list[dict]] = field(default_factory=lambda: {k: list(v) for k, v in _FIXTURE_TRANSACTIONS.items()})

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.5

    def fetch_transactions(self, ticker: str) -> list[dict] | None:
        """Return the parsed Form 4 transactions for `ticker` (offline → fixture, online → live SEC EDGAR).

        Three honest outcomes (None = "no observation", a list = "this is the data"):
          * None  — the ticker is NOT in the curated CIK map (untracked), OR the live fetch FAILED (network/
            parse error). Both are gaps the caller renders as value=None — NEVER a fabricated 0. The error
            path is deliberately fused with the untracked path here because both mean "we have no observation";
            what matters is that a FAILED fetch never yields a (possibly partial) list that becomes a real 0.
          * []    — a SUCCESSFUL fetch (or fixture) for a TRACKED ticker that genuinely has no transactions.
            This is a real empty reading; net_buy_ratio([]) renders it as None (no in-window P/S activity),
            which is correct — but it came from data we actually saw, not from a failure.
        """
        key = ticker.upper()
        if key not in _CIK_BY_TICKER:
            return None  # not tracked → None (gap, never 0)
        if self.offline:
            return list(self._fixture.get(key, []))
        # Live path: _fetch_form4_transactions returns None on FETCH FAILURE (no observation) vs [] on a
        # genuine empty filing. Propagate that distinction unchanged.
        return _fetch_form4_transactions(_CIK_BY_TICKER[key], timeout=self.timeout)

    def query(self, scope: str, as_of: datetime, *, limit: int = 4096) -> SourceFeature:
        """Latest net insider-buy ratio knowable at `as_of` for the equity ticker `scope`.

        Aggregates only filings whose acceptanceDateTime <= as_of within the trailing window. The
        SourceFeature.available_at is the LATEST acceptanceDateTime among the filings actually used (None when
        none are used). A ticker with no in-window open-market P/S filings → value=None (NEVER fabricated 0).
        """
        del limit  # part of the protocol; this source aggregates the whole window
        ticker = scope.upper()
        transactions = self.fetch_transactions(ticker)
        if transactions is None:
            # NO OBSERVATION — untracked ticker OR a failed live fetch (network/parse error). Honest no-data:
            # value=None, available_at=None. This is the data-honesty split: a fetch FAILURE never falls
            # through to net_buy_ratio (which could fabricate a 0/non-None ratio from partial data); only a
            # genuine empty list ([]) reaches the aggregation below and correctly renders as None.
            return SourceFeature(
                name=self.name,
                scope=ticker,
                as_of=as_of,
                value=None,
                available_at=None,
                confidence=self.confidence,
                transform_version=self.transform_version,
                prior=self.prior,
                low_confidence=self.low_confidence,
            )
        value = net_buy_ratio(transactions, as_of=as_of, window_days=self.window_days)
        available_at = (
            _latest_used_available_at(transactions, as_of=as_of, window_days=self.window_days)
            if value is not None
            else None
        )
        return SourceFeature(
            name=self.name,
            scope=ticker,
            as_of=as_of,
            value=float(value) if value is not None else None,
            available_at=available_at,
            confidence=self.confidence,
            transform_version=self.transform_version,
            prior=self.prior,
            low_confidence=self.low_confidence,
        )
