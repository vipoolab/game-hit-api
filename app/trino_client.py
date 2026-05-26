"""Trino connection helper.

Security notes:
- Credentials come from env vars (loaded by config.py) — never hardcoded.
- The trino library logs at DEBUG (not INFO) so the `Authorization: Basic ...`
  header is NOT emitted under our default INFO log level.
- We log only the first 120 chars of SQL — enough to debug shape, not enough
  to leak data.
- Connection errors are re-raised with the host stripped to prevent error
  messages from leaking the warehouse hostname into responses or external logs.
"""
from __future__ import annotations

import logging
from typing import Any

import trino
from trino.auth import BasicAuthentication

from .config import TrinoConfig

log = logging.getLogger(__name__)

# Belt-and-braces: force trino's internal HTTP client to never log auth at INFO.
# (The library already does this, but be explicit so a future log-level change
# in this app doesn't accidentally start emitting Authorization headers.)
logging.getLogger("trino").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class TrinoQueryError(Exception):
    """Sanitized wrapper around trino errors — drops connection-string details."""


def _make_connection(cfg: TrinoConfig) -> trino.dbapi.Connection:
    auth = BasicAuthentication(cfg.user, cfg.password) if cfg.password else None
    return trino.dbapi.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        catalog=cfg.catalog,
        http_scheme=cfg.scheme,
        auth=auth,
        request_timeout=cfg.request_timeout,
        verify=True,
    )


def _sanitize_error(err: Exception, host: str) -> str:
    """Strip the Trino hostname from error messages to keep it out of bubbled-up
    exceptions / API responses. The host stays in our own log.info (which we
    control), but trino library exceptions can otherwise reach response bodies.
    """
    msg = str(err)
    if host:
        msg = msg.replace(host, "<trino-host>")
    return msg


def run_query(cfg: TrinoConfig, sql: str) -> tuple[list[str], list[list[Any]]]:
    """Run a SELECT and return (columns, rows). Raises TrinoQueryError on failure."""
    log.info("Trino query: %s...", " ".join(sql.split())[:120])
    try:
        conn = _make_connection(cfg)
    except Exception as e:
        raise TrinoQueryError(f"Connection failed: {_sanitize_error(e, cfg.host)}") from e

    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows
    except Exception as e:
        raise TrinoQueryError(f"Query failed: {_sanitize_error(e, cfg.host)}") from e
    finally:
        try:
            conn.close()
        except Exception:
            pass
