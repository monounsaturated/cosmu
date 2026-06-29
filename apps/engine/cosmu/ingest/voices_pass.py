# intent: the CREDIBILITY PASS (realtime-data-lane epic P2) — one bounded cron tick that runs the dormant
# "PageRank for credibility" pipeline end-to-end on the PRE-REGISTERED voice panel: Phase 0 pull each voice's
# recent timeline (key-gated providers) → durable, deduped post records in `market_events` (provider="voices",
# available_at = receipt) → Phase 1 LLM claim extraction on NEW posts only (hard per-pass caps bound the bill)
# → typed rows in `voice_claims` → Phase 2/3 DETERMINISTIC scoring (Brier skill vs base rate, sample-shrunk;
# primacy; skill-anchored PageRank) → ONE flat human-readable row per voice in `voice_scoreboard` + the two
# registered PIT features (`author_authority`, `authority_weighted_claim_signal`) appended to `alt_data`.
# inputs: the knowledge Store + injectable providers/extractor/bars/now; outputs: a VoicesPassReport + the
# tables above. invariants: PRE-REGISTRATION (only panel voices are pulled — never a post-hoc viral account);
# the LLM extracts STRUCTURE only, never scores or touches money; spend is bounded by MAX_* caps and by the
# market_events dedup (an already-stored post is never re-extracted — re-runs are free); keyless runs degrade
# honestly everywhere ([] posts / no claims / a scoreboard row with zeros — never fabricated skill);
# deterministic + offline-testable (every seam injectable). `python3 -m cosmu.ingest.voices_pass`.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cosmu.config.settings import Settings, get_settings
from cosmu.config.voices import (
    ENTITY_BARS_SYMBOL,
    MAX_EXTRACTIONS_PER_PASS,
    MAX_POSTS_PER_VOICE_PER_PASS,
    VOICE_PANEL,
    Voice,
)
from cosmu.data.events_store import MarketEvent, PgEventsStore
from cosmu.data.market import MarketDataProvider, default_crypto_reference
from cosmu.data.sources.voices import (
    RedditVoiceProvider,
    RssVoiceProvider,
    VoicePost,
    XaiVoiceProvider,
)
from cosmu.knowledge.store import Store, utcnow
from cosmu.mind import claims as claims_mod
from cosmu.mind.authority import Event, authority_weighted_signal, compute_authority
from cosmu.mind.claims import Claim, ClaimExtractor, build_claim_extractor_from_settings

logger = logging.getLogger("cosmu.ingest.voices_pass")

# Pinned into every persisted claim so a downstream survivor that trains on these features stays reproducible.
CLAIMS_EXTRACTOR_VERSION = "voice-claims-v1"


@dataclass
class VoicesPassReport:
    voices: int = 0
    posts_fetched: int = 0
    posts_new: int = 0            # not seen in market_events before this pass
    posts_extracted: int = 0      # sent to the LLM this pass (≤ MAX_EXTRACTIONS_PER_PASS)
    claims_new: int = 0
    claims_total: int = 0         # all stored claims the scoring ran on
    scoreboard_rows: int = 0
    features_written: int = 0
    conviction_proposals: int = 0  # propose-only authority-conviction proposals produced this pass (human arms)
    errors: list[str] = field(default_factory=list)


def _post_event(post: VoicePost) -> MarketEvent:
    """A timeline post as a durable market_events row. Identity = (platform, handle, post_id) — the hash is
    set explicitly so an edited/re-scraped copy of the same post can never double-count."""
    import hashlib

    return MarketEvent(
        provider="voices",
        source=post.handle,
        symbols=(),
        ts=post.ts,
        available_at=post.available_at,
        title=post.text[:500],
        content_hash=hashlib.sha256(f"{post.platform}|{post.handle}|{post.post_id}".encode()).hexdigest(),
        event_type="voice_post",
    )


def _default_providers(settings: Settings) -> dict[str, object]:
    return {
        "x": XaiVoiceProvider(api_key=settings.xai_api_key or ""),
        "reddit": RedditVoiceProvider(),
        "rss": RssVoiceProvider(),
    }


def _existing_hashes(store: Store, hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    placeholders = ",".join("?" for _ in hashes)
    rows = store.rows(
        f"SELECT content_hash FROM market_events WHERE provider = 'voices' AND content_hash IN ({placeholders})",
        tuple(hashes),
    )
    return {r["content_hash"] for r in rows}


def _persist_claims(store: Store, claims: list[Claim]) -> int:
    """Insert NEW claims only (deduped on the table's UNIQUE key, pre-filtered here so the batch never trips
    the constraint). Returns the number written."""
    if not claims:
        return 0
    keys = sorted({c.post_id for c in claims})
    placeholders = ",".join("?" for _ in keys)
    existing = {
        (r["post_id"], r["entity"], r["direction"], r["horizon"])
        for r in store.rows(
            f"SELECT post_id, entity, direction, horizon FROM voice_claims WHERE post_id IN ({placeholders})",
            tuple(keys),
        )
    }
    now = utcnow()
    rows = []
    seen = set(existing)
    for c in claims:
        key = (c.post_id, c.entity, c.direction, c.horizon)
        if key in seen:
            continue
        seen.add(key)
        rows.append((c.handle, c.platform, c.post_id, c.entity, c.direction, c.horizon, c.horizon_days,
                     float(c.conviction), c.ts.isoformat(), c.quote, c.url, CLAIMS_EXTRACTOR_VERSION, now))
    if rows:
        with store.batch() as writer:
            writer.insert_many(
                "voice_claims",
                ["handle", "platform", "post_id", "entity", "direction", "horizon", "horizon_days",
                 "conviction", "ts", "quote", "url", "extractor_version", "ingested_at"],
                rows,
            )
    return len(rows)


def _load_all_claims(store: Store) -> list[Claim]:
    rows = store.rows("SELECT * FROM voice_claims ORDER BY ts, post_id, entity")
    out: list[Claim] = []
    for r in rows:
        ts = datetime.fromisoformat(str(r["ts"]))
        out.append(Claim(
            handle=str(r["handle"]), platform=str(r["platform"]), post_id=str(r["post_id"]),
            entity=str(r["entity"]), direction=str(r["direction"]), horizon=str(r["horizon"]),
            horizon_days=int(r["horizon_days"]), conviction=float(r["conviction"]),
            ts=ts if ts.tzinfo else ts.replace(tzinfo=UTC), quote=str(r.get("quote") or ""),
            url=str(r.get("url") or ""),
        ))
    return out


# The inverse of the entity→venue-symbol routing: a market_events row affects venue symbols ("BTCUSDT"), but a
# claim's lead-lag is keyed by entity ("BTC"). Built once from ENTITY_BARS_SYMBOL so the two stay in lock-step.
_SYMBOL_TO_ENTITY: dict[str, str] = {sym: ent for ent, sym in ENTITY_BARS_SYMBOL.items()}


def _load_event_timeline(store: Store, entities: set[str], *, now: datetime) -> list[Event]:
    """Build the EXTERNAL event timeline that turns each claim's lead-lag from latent to live. A market_events row
    that PRECEDES a same-entity claim is the claim ECHOING news; one that FOLLOWS it is the claim having FORESIGHT.
    We read durable `market_events` (news/on-chain/etc.), map each row's affected venue symbols back to a claim
    entity, and emit one Event per (entity, ts).

    Two deliberate exclusions keep this honest:
      * provider='voices' is SKIPPED — those rows ARE the voice posts being scored; using them as the event
        timeline would let a claim be its own evidence (circular). The timeline must be an INDEPENDENT signal.
      * market-wide rows (no symbols) and rows on unmapped symbols are dropped (named no_data, never guessed).
    PIT-honest: only events with ts <= now are returned (compute_authority filters again, this just bounds I/O).
    Offline/degrade-safe: a missing table or empty store yields [] (the pass falls back to lead_lag='none')."""
    if not entities:
        return []
    try:
        rows = store.rows(
            "SELECT provider, symbols, ts, title FROM market_events "
            "WHERE provider <> 'voices' AND ts <= ? ORDER BY ts",
            (now.isoformat(),),
        )
    except Exception:  # noqa: BLE001 — table may not exist on a fresh/legacy store: no timeline this pass
        return []
    out: list[Event] = []
    for r in rows:
        raw = r.get("symbols")
        if isinstance(raw, str):
            try:
                symbols = json.loads(raw) if raw else []
            except (TypeError, ValueError):
                symbols = []
        else:
            symbols = list(raw or [])
        seen_entities: set[str] = set()
        for sym in symbols:
            entity = _SYMBOL_TO_ENTITY.get(str(sym))
            if entity is None or entity not in entities or entity in seen_entities:
                continue
            seen_entities.add(entity)
            ts = datetime.fromisoformat(str(r["ts"]))
            out.append(Event(ts=ts if ts.tzinfo else ts.replace(tzinfo=UTC), entity=entity,
                             label=str(r.get("title") or "")[:120]))
    return out


def _bars_by_entity(entities: set[str], provider: MarketDataProvider) -> dict[str, list]:
    """Daily bars per claim entity via the entity→venue-symbol routing. An unmapped/unfetchable entity gets
    no bars — its claims resolve as no_data (named, never guessed)."""
    out: dict[str, list] = {}
    for entity in sorted(entities):
        symbol = ENTITY_BARS_SYMBOL.get(entity)
        if symbol is None:
            continue
        try:
            bars = provider.fetch_bars(symbol, "1d", limit=400)
        except Exception:  # noqa: BLE001 — offline: the entity resolves as no_data this pass
            bars = []
        if bars:
            out[entity] = bars
    return out


def _upsert_scoreboard(store: Store, *, voice: Voice, n_posts: int, n_claims: int, state, now: str) -> None:  # noqa: ANN001
    """One flat row per voice — the operator-readable surface. Plain columns; NULL skill until claims resolve
    (a zero would read as 'tested and unskilled', which an untested voice is not)."""
    rec = state.track_records.get(voice.handle) if state is not None else None
    authority = state.author_authority.get(voice.handle) if state is not None else None
    primacy = state.primacy_rate.get(voice.handle) if state is not None else None
    with store.batch() as writer:
        writer.execute(
            """
            INSERT INTO voice_scoreboard (handle, platform, n_posts, n_claims, n_resolved, hit_rate,
              base_hit_rate, excess_hit_rate, brier_skill_score, calibration_error, skill, authority,
              primacy_rate, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (platform, handle) DO UPDATE SET
              n_posts = excluded.n_posts, n_claims = excluded.n_claims, n_resolved = excluded.n_resolved,
              hit_rate = excluded.hit_rate, base_hit_rate = excluded.base_hit_rate,
              excess_hit_rate = excluded.excess_hit_rate, brier_skill_score = excluded.brier_skill_score,
              calibration_error = excluded.calibration_error, skill = excluded.skill,
              authority = excluded.authority, primacy_rate = excluded.primacy_rate,
              updated_at = excluded.updated_at
            """,
            (
                voice.handle, voice.platform, n_posts, n_claims,
                rec.n_resolved if rec else 0,
                rec.hit_rate if rec and rec.n_resolved else None,
                rec.base_hit_rate if rec and rec.n_resolved else None,
                rec.excess_hit_rate if rec and rec.n_resolved else None,
                rec.brier_skill_score if rec and rec.n_resolved else None,
                rec.calibration_error if rec and rec.n_resolved else None,
                rec.skill if rec and rec.n_resolved else None,
                authority, primacy, now,
            ),
        )


def run_voices_pass(
    store: Store | None = None,
    *,
    panel: tuple[Voice, ...] | None = None,
    providers: dict[str, object] | None = None,
    extractor: ClaimExtractor | None = None,
    bars_provider: MarketDataProvider | None = None,
    now: datetime | None = None,
    max_posts_per_voice: int = MAX_POSTS_PER_VOICE_PER_PASS,
    max_extractions: int = MAX_EXTRACTIONS_PER_PASS,
) -> VoicesPassReport:
    """ONE bounded credibility tick. Safe to run on any cadence: post storage is deduped, extraction runs on
    NEW posts only (capped), and scoring is a deterministic recompute over the stored corpus."""
    settings = get_settings()
    store = store or Store(settings)
    panel = panel if panel is not None else VOICE_PANEL
    providers = providers if providers is not None else _default_providers(settings)
    extractor = extractor if extractor is not None else build_claim_extractor_from_settings(settings)
    bars_provider = bars_provider or default_crypto_reference()
    now = now or datetime.now(tz=UTC)
    events_store = PgEventsStore(store)
    report = VoicesPassReport(voices=len(panel))

    # Phase 0 + 1: pull timelines, store NEW posts durably, extract claims from the new ones (capped).
    extraction_budget = max_extractions
    all_pass_posts: list[VoicePost] = []
    for voice in panel:
        provider = providers.get(voice.platform)
        if provider is None:
            report.errors.append(f"no provider for platform {voice.platform!r} ({voice.handle})")
            continue
        try:
            posts = provider.fetch_timeline(voice.handle, limit=max_posts_per_voice)
        except Exception as exc:  # noqa: BLE001 — one dead voice must never abort the pass
            report.errors.append(f"{voice.handle}: {exc}")
            continue
        report.posts_fetched += len(posts)
        all_pass_posts.extend(posts)
        if not posts:
            continue
        events = [_post_event(p) for p in posts]
        existing = _existing_hashes(store, [e.content_hash for e in events])
        fresh_posts = [p for p, e in zip(posts, events, strict=True) if e.content_hash not in existing]
        report.posts_new += len(fresh_posts)
        events_store.append(events)
        if extraction_budget > 0 and fresh_posts:
            batch = fresh_posts[:extraction_budget]
            extraction_budget -= len(batch)
            report.posts_extracted += len(batch)
            extracted = extractor.extract([
                claims_mod.VoicePost(handle=p.handle, platform=p.platform, post_id=p.post_id,
                                     text=p.text, ts=p.ts, url=p.url)
                for p in batch
            ])
            report.claims_new += _persist_claims(store, extracted)

    # Phase 2 + 3: deterministic recompute over the WHOLE stored claim corpus (never just this pass).
    claims = _load_all_claims(store)
    report.claims_total = len(claims)
    state = None
    if claims:
        entities = {c.entity for c in claims}
        bars = _bars_by_entity(entities, bars_provider)
        posts_for_graph = [
            claims_mod.VoicePost(handle=p.handle, platform=p.platform, post_id=p.post_id,
                                 text=p.text, ts=p.ts, url=p.url)
            for p in all_pass_posts
        ]
        # The INDEPENDENT event timeline (news/on-chain) so primacy/lead-lag activates: a claim that PRECEDES a
        # same-entity event is foresight (evidence); one that FOLLOWS it is an echo. Without this the lead-lag is
        # latent ('none' for every claim) and the foresight-vs-echo separation never fires.
        events = _load_event_timeline(store, entities, now=now)
        state = compute_authority(claims, bars_by_entity=bars, posts=posts_for_graph, events=events, as_of=now)

        # The two registered PIT features (availability == observation: a credibility judgement is knowable
        # only when made). Appended every pass → the series accrues real recorded-live history for the Gate.
        from cosmu.data.altdata import AltDataPoint, PgAltDataStore

        alt = PgAltDataStore(store)
        for handle, value in sorted(state.author_authority.items()):
            alt.append("social_authority", handle, "author_authority",
                       [AltDataPoint(ts=now, available_at=now, value=float(value))])
            report.features_written += 1
        for entity in sorted({c.entity for c in claims}):
            signal = authority_weighted_signal(state, entity, as_of=now)
            if signal is None:
                continue  # no active claim window → honest abstain, never a fabricated zero
            alt.append("social_authority", entity, "authority_weighted_claim_signal",
                       [AltDataPoint(ts=now, available_at=now, value=float(signal))])
            report.features_written += 1

        # CONSUMER: turn each followed account's fresh, actionable, non-echo call into a propose-only conviction
        # proposal (sized by authority × EV, hard max-loss cap) for a HUMAN to review + arm. Schema-probe gated
        # (cosmu/conviction/store) — a pre-migration prod has no `conviction_proposals` table, so this no-ops and
        # the /conviction queue stays honest-empty. NOTHING here arms or moves money; it only writes proposals.
        try:
            from cosmu.conviction.producer import refresh_conviction_proposals

            produced = refresh_conviction_proposals(
                store,
                claims=claims,
                bars_by_entity=bars,  # the same per-entity bars Phase 2/3 just resolved against
                accounts=[v.handle for v in panel],
                now=now,
                posts=posts_for_graph,
                events=events,
            )
            report.conviction_proposals = len(produced)
        except Exception as exc:  # noqa: BLE001 — the conviction consumer must never abort the credibility pass
            report.errors.append(f"conviction: {exc}")

    # The scoreboard: one flat row per PANEL voice (zeros/NULLs are honest states, not absences).
    now_iso = utcnow()
    for voice in panel:
        n_posts = store.row(
            "SELECT COUNT(*) AS n FROM market_events WHERE provider = 'voices' AND source = ?", (voice.handle,)
        )
        n_claims = store.row("SELECT COUNT(*) AS n FROM voice_claims WHERE handle = ?", (voice.handle,))
        _upsert_scoreboard(
            store, voice=voice,
            n_posts=int(n_posts["n"]) if n_posts else 0,
            n_claims=int(n_claims["n"]) if n_claims else 0,
            state=state, now=now_iso,
        )
        report.scoreboard_rows += 1

    store.append_event(
        actor="ingest", kind="voices_pass_completed", ref_type="voices", ref_id="panel",
        payload={"voices": report.voices, "posts_fetched": report.posts_fetched, "posts_new": report.posts_new,
                 "posts_extracted": report.posts_extracted, "claims_new": report.claims_new,
                 "claims_total": report.claims_total, "features_written": report.features_written,
                 "conviction_proposals": report.conviction_proposals, "errors": report.errors[:10]},
    )
    return report


def _main(argv: list[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(
        description="Run one bounded credibility pass over the pre-registered voice panel (Phase 0-3)."
    ).parse_args(argv)
    report = run_voices_pass()
    print(
        f"VOICES PASS — voices={report.voices} posts={report.posts_fetched} (new={report.posts_new}, "
        f"extracted={report.posts_extracted}) claims new={report.claims_new}/total={report.claims_total} "
        f"scoreboard={report.scoreboard_rows} features={report.features_written} "
        f"conviction={report.conviction_proposals} errors={len(report.errors)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
