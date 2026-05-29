"""SQL queries against v2 game stream — global scope, last N days.

Both queries return ONLY unique_players (the ranking metric). spins and
bet_volume were dropped from the API surface so we drop them from the
warehouse query too — fewer bytes over the wire, no Decimal handling
needed downstream.
"""
from __future__ import annotations


def provider_rollup_sql(window_days: int) -> str:
    """Unique players per provider over the last N days.

    `unique_players` is computed at provider level (not summable from games)
    because a single player can play many games within the same provider.
    """
    return f"""
        SELECT
          provider,
          COALESCE(NULLIF(TRIM(fullname_provider), ''), provider) AS provider_fullname,
          COUNT(DISTINCT username) AS unique_players
        FROM delta.default.v2_silver_precal_prod_stream
        WHERE date BETWEEN CAST(CURRENT_DATE - INTERVAL '{int(window_days)}' DAY AS VARCHAR)
                        AND CAST(CURRENT_DATE AS VARCHAR)
        GROUP BY provider, COALESCE(NULLIF(TRIM(fullname_provider), ''), provider)
    """


def game_rollup_sql(window_days: int) -> str:
    """Unique players per (provider, game) over the last N days."""
    return f"""
        SELECT
          provider,
          game_name,
          COUNT(DISTINCT username) AS unique_players
        FROM delta.default.v2_silver_precal_prod_stream
        WHERE date BETWEEN CAST(CURRENT_DATE - INTERVAL '{int(window_days)}' DAY AS VARCHAR)
                        AND CAST(CURRENT_DATE AS VARCHAR)
          AND game_name IS NOT NULL
          AND TRIM(game_name) <> ''
        GROUP BY provider, game_name
    """
