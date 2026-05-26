"""Centralized config loaded from env (.env if present)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from a chain of locations, in priority order (first wins).
# Lets users reuse the casino-trino skill credentials they already have set up.
_ENV_CANDIDATES = [
    PROJECT_ROOT / ".env",
    Path.home() / ".config" / "casino-trino" / ".env",
    Path.home() / ".casino-trino.env",
]
for _p in _ENV_CANDIDATES:
    if _p.exists():
        load_dotenv(_p, override=False)


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name, default)
    return v if v not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class TrinoConfig:
    host: str
    port: int
    user: str
    password: str | None
    catalog: str
    scheme: str
    request_timeout: int


@dataclass(frozen=True)
class AppConfig:
    api_host: str
    api_port: int
    window_days: int
    cron_hour: str
    cron_minute: str
    games_per_provider: int
    cache_file: Path
    refresh_token: str | None
    trino: TrinoConfig


def load_config() -> AppConfig:
    host = _env("TRINO_HOST")
    user = _env("TRINO_USER")
    if not host or not user:
        raise RuntimeError(
            "Missing required env vars: TRINO_HOST and TRINO_USER must be set. "
            "Copy .env.example to .env and fill in your Trino credentials."
        )

    cache_raw = _env("HIT_CACHE_FILE", "data/hits.json")
    cache_path = Path(cache_raw)
    if not cache_path.is_absolute():
        cache_path = PROJECT_ROOT / cache_path

    # PORT (uppercase, no prefix) is the convention used by Railway, Heroku,
    # Fly, Render, Cloud Run — it takes priority over API_PORT.
    port = _env_int("PORT", _env_int("API_PORT", 8000))

    return AppConfig(
        api_host=_env("API_HOST", "0.0.0.0"),
        api_port=port,
        window_days=_env_int("HIT_WINDOW_DAYS", 30),
        cron_hour=_env("HIT_REFRESH_CRON_HOUR", "3"),
        cron_minute=_env("HIT_REFRESH_CRON_MINUTE", "5"),
        games_per_provider=_env_int("HIT_GAMES_PER_PROVIDER", 50),
        cache_file=cache_path,
        refresh_token=_env("REFRESH_TOKEN"),
        trino=TrinoConfig(
            host=host,
            port=_env_int("TRINO_PORT", 443),
            user=user,
            password=_env("TRINO_PASSWORD"),
            catalog=_env("TRINO_CATALOG", "delta"),
            scheme=_env("TRINO_HTTP_SCHEME", "https"),
            request_timeout=_env_int("TRINO_REQUEST_TIMEOUT", 120),
        ),
    )
