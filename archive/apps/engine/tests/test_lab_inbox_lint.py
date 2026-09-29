# The offline, read-only inbox LINT: walk strategies/inbox, validate + facet each spec, and cluster near-dups
# BEFORE a boot-scan or the Gate. Covers (a) a valid spec PASSes, (b) an invalid spec is caught FAILED (no crash),
# (c) two near-duplicate specs land in one dup-cluster, (d) two distinct specs are NOT clustered. Fully offline:
# no Store, no DB, no network, no inbox mutation.

from __future__ import annotations

import json
from pathlib import Path

from cosmu.evolution.seeder import seed_carry_spec, seed_meanrev_spec, seed_momentum_spec
from cosmu.lab.inbox_lint import lint_inbox, render_table, to_json


def _write(inbox: Path, filename: str, spec_dict: dict) -> None:
    (inbox / filename).write_text(json.dumps(spec_dict), encoding="utf-8")


def _momentum_variant(name: str, mom_floor_hi: float) -> dict:
    """A momentum spec identical in STRUCTURE (same entry feature set {ret_Nd, adx}, same bar_size) to the base
    seed but with a different name + a tweaked param range — exactly the near-duplicate shape that burns the
    Gate's FDR budget (structural_distance == 0)."""
    spec = seed_momentum_spec().model_dump(mode="json")
    spec["name"] = name
    spec["param_space"]["mom_floor"]["hi"] = mom_floor_hi
    return spec


def test_valid_spec_passes(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write(inbox, "carry.json", seed_carry_spec().model_dump(mode="json"))

    report = lint_inbox(inbox)
    assert report.scanned == 1
    assert len(report.passed) == 1 and not report.failed
    row = report.passed[0]
    assert row.status == "PASS" and row.issues == []
    # Facts are surfaced, derived from the spec (never hand-tagged).
    assert row.kind == "json"
    assert row.signal_family and row.signal_family != "—"
    assert row.entry_mechanism != "—"
    assert row.features  # a carry spec references at least funding_rate


def test_invalid_spec_is_caught_not_crashed(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    # (1) an unknown-feature spec: validate_spec rejects it but it still parses to a typed spec.
    bad = seed_momentum_spec().model_dump(mode="json")
    bad["name"] = "Unknown-feature spec"
    bad["entry"][0]["feature"]["name"] = "totally_not_a_registry_feature"
    _write(inbox, "bad-feature.json", bad)
    # (2) a structurally-malformed file (not even valid JSON) — must be reported FAILED, never crash the lint.
    (inbox / "garbage.json").write_text("{ this is not json", encoding="utf-8")

    report = lint_inbox(inbox)
    assert report.scanned == 2
    assert not report.passed and len(report.failed) == 2
    by_name = {r.filename: r for r in report.failed}
    assert any("unknown_feature" in i for i in by_name["bad-feature.json"].issues)
    # the malformed file is FAILED with a parse_error reason, not an exception
    assert any("parse_error" in i or "lint_error" in i for i in by_name["garbage.json"].issues)
    # issues are de-duplicated (validate_spec can emit the same reason twice)
    assert len(set(by_name["bad-feature.json"].issues)) == len(by_name["bad-feature.json"].issues)


def test_near_duplicates_cluster_together(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write(inbox, "mom-a.json", _momentum_variant("Momentum A", 0.12))
    _write(inbox, "mom-b.json", _momentum_variant("Momentum B", 0.20))  # same entry features → distance 0

    report = lint_inbox(inbox)
    assert len(report.passed) == 2 and not report.failed
    # exactly one near-dup cluster holding BOTH files
    assert len(report.dup_clusters) == 1
    members = next(iter(report.dup_clusters.values()))
    assert set(members) == {"mom-a.json", "mom-b.json"}
    # each row points at the other as its nearest neighbour at distance ~0 and shares a cluster id
    for r in report.passed:
        assert r.cluster >= 0
        assert r.nearest_dist is not None and r.nearest_dist < 0.25
    assert report.passed[0].cluster == report.passed[1].cluster


def test_distinct_specs_not_clustered(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    # momentum (entry {ret_Nd, adx}) vs mean-reversion (a disjoint entry feature set) → distance well above 0.25
    _write(inbox, "mom.json", seed_momentum_spec().model_dump(mode="json"))
    _write(inbox, "meanrev.json", seed_meanrev_spec().model_dump(mode="json"))

    report = lint_inbox(inbox)
    assert len(report.passed) == 2 and not report.failed
    assert report.dup_clusters == {}  # nothing clustered
    for r in report.passed:
        assert r.cluster == -1
        assert r.nearest_dist is not None and r.nearest_dist >= 0.25


def test_render_and_json_shape(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write(inbox, "mom-a.json", _momentum_variant("Momentum A", 0.12))
    _write(inbox, "mom-b.json", _momentum_variant("Momentum B", 0.20))
    bad = seed_momentum_spec().model_dump(mode="json")
    bad["entry"][0]["feature"]["name"] = "totally_not_a_registry_feature"
    _write(inbox, "bad.json", bad)

    report = lint_inbox(inbox)
    table = render_table(report)
    assert "INBOX LINT" in table and "STATUS" in table and "NEAR-DUPLICATE CLUSTERS" in table and "FAIL REASONS" in table

    payload = to_json(report)
    assert payload["scanned"] == 3
    assert {"inbox_dir", "scanned", "passed", "failed", "dup_clusters"} <= set(payload)
    assert len(payload["passed"]) == 2 and len(payload["failed"]) == 1
    # dup_clusters is JSON-serializable (string keys) and round-trips
    assert json.loads(json.dumps(payload)) == payload


def test_missing_inbox_is_safe(tmp_path):
    report = lint_inbox(tmp_path / "does-not-exist")
    assert report.scanned == 0 and report.passed == [] and report.failed == []
