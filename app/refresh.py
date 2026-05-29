"""Refresh logic: query Trino, merge provider + game rollups, rank, save cache."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from .cache import HitsCache
from .config import AppConfig
from .queries import game_rollup_sql, provider_rollup_sql
from .trino_client import run_query

log = logging.getLogger(__name__)


def _build_payload(
    *,
    window_days: int,
    games_per_provider: int,
    provider_rows: list[list[Any]],
    game_rows: list[list[Any]],
) -> dict[str, Any]:
    # Index games by provider code. Each row is (provider, game_id, game_name,
    # unique_players) — for slot games game_id is the stable warehouse ID,
    # for sport/lottery game_id is per-session.
    games_by_provider: dict[str, list[dict[str, Any]]] = {}
    for code, gid, name, players in game_rows:
        if not code:
            continue
        games_by_provider.setdefault(code, []).append({
            "game_id": gid,
            "game_name": name,
            "unique_players": int(players or 0),
        })

    providers: list[dict[str, Any]] = []
    for code, fullname, players in provider_rows:
        if not code:
            continue
        games = games_by_provider.get(code, [])
        # Tiebreak by game_name then game_id asc so ordering is stable run-to-run
        games.sort(key=lambda g: (
            -g["unique_players"],
            g["game_name"] or "",
            g["game_id"] or "",
        ))
        if games_per_provider > 0:
            games = games[:games_per_provider]
        for idx, g in enumerate(games, start=1):
            g["rank"] = idx
        providers.append({
            "provider_code": code,
            "provider_fullname": fullname or code,
            "unique_players": int(players or 0),
            "game_count": len(games),
            "games": games,
        })

    # Tiebreak by provider_code asc for stable ordering
    providers.sort(key=lambda p: (-p["unique_players"], p["provider_code"]))
    for idx, p in enumerate(providers, start=1):
        p["rank"] = idx

    return {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "window_days": window_days,
        "metric": "unique_players",
        "scope": "global",
        "provider_count": len(providers),
        "providers": providers,
    }


def refresh_once(cfg: AppConfig, cache: HitsCache) -> dict[str, Any]:
    """Run the two aggregation queries, build the payload, store + persist it.

    Returns the new payload. Raises on Trino errors so the scheduler logs them.
    """
    log.info("Refresh starting (window=%dd)", cfg.window_days)
    started = time.monotonic()

    p_cols, provider_rows = run_query(cfg.trino, provider_rollup_sql(cfg.window_days))
    t1 = time.monotonic()
    log.info("Provider rollup: %d rows in %.1fs", len(provider_rows), t1 - started)

    g_cols, game_rows = run_query(cfg.trino, game_rollup_sql(cfg.window_days))
    t2 = time.monotonic()
    log.info("Game rollup: %d rows in %.1fs", len(game_rows), t2 - t1)

    payload = _build_payload(
        window_days=cfg.window_days,
        games_per_provider=cfg.games_per_provider,
        provider_rows=provider_rows,
        game_rows=game_rows,
    )
    cache.set(payload)
    log.info("Refresh complete: %d providers, total %.1fs",
             payload["provider_count"], time.monotonic() - started)
    return payload
