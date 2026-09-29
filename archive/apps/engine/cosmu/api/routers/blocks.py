# intent: read-only API over the building-block registry — the block leaderboard + per-version blocks and
# similar strategies; inputs: none / a version_id; outputs: BlockLeaderboardResponse / VersionBlocksResponse;
# invariants: OBSERVATIONAL only (never funds/kills), fail-open `available=False` while the 2026-06-11
# migration hasn't been applied to the store, never fabricates a row.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import BlockLeaderboardResponse, BlockStat, SimilarVersion, VersionBlocksResponse
from cosmu.knowledge.block_registry import block_leaderboard, blocks_available, versions_sharing_blocks

router = APIRouter()


@router.get("/blocks", response_model=BlockLeaderboardResponse)
def blocks() -> BlockLeaderboardResponse:
    if not blocks_available(store):
        return BlockLeaderboardResponse(available=False, rows=[])
    rows = [BlockStat(**r) for r in block_leaderboard(store)]
    return BlockLeaderboardResponse(available=True, rows=rows)


@router.get("/blocks/version/{version_id}", response_model=VersionBlocksResponse)
def version_blocks(version_id: str) -> VersionBlocksResponse:
    if not blocks_available(store):
        return VersionBlocksResponse(version_id=version_id, available=False, blocks=[], similar=[])
    stats = {r["block_hash"]: r for r in block_leaderboard(store, min_n=1, limit=10_000)}
    mine = store.rows(
        "SELECT vb.block_hash, sb.kind, sb.label FROM version_blocks vb "
        "JOIN strategy_blocks sb ON sb.block_hash = vb.block_hash "
        "WHERE vb.strategy_version_id = ? ORDER BY sb.kind, sb.label",
        (version_id,),
    )
    blocks_out = [
        BlockStat(
            block_hash=r["block_hash"],
            kind=r["kind"],
            label=r["label"],
            n_versions=int(stats.get(r["block_hash"], {}).get("n_versions", 1)),
            n_funded=int(stats.get(r["block_hash"], {}).get("n_funded", 0)),
            funded_rate=float(stats.get(r["block_hash"], {}).get("funded_rate", 0.0)),
        )
        for r in mine
    ]
    similar = [
        SimilarVersion(
            version_id=r["version_id"], name=r["name"], status=r["status"], shared_blocks=int(r["shared_blocks"])
        )
        for r in versions_sharing_blocks(store, version_id)
    ]
    return VersionBlocksResponse(version_id=version_id, available=True, blocks=blocks_out, similar=similar)
