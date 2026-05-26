"""Trino connection helper."""
from __future__ import annotations

import logging
from typing import Any, Iterable

import trino
from trino.auth import BasicAuthentication

from .config import TrinoConfig

log = logging.getLogger(__name__)


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


def run_query(cfg: TrinoConfig, sql: str) -> tuple[list[str], list[list[Any]]]:
    """Run a SELECT and return (columns, rows). Caller handles errors."""
    log.info("Trino query: %s...", " ".join(sql.split())[:120])
    conn = _make_connection(cfg)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, rows
    finally:
        conn.close()
