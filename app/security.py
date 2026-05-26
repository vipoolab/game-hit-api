"""Access-code gate for data endpoints.

A simple shared-code gate driven by `ACCESS_CODE` env var. The caller sends
the code as either:

- Query parameter: `?code=<value>`  ← shows up as a normal query param in /docs
- HTTP header:     `X-Access-Code: <value>`

`code` is declared as a `Query` parameter on the dependency itself, so any
endpoint using `Depends(require_access_code)` exposes it as a regular
endpoint parameter in the generated OpenAPI schema (visible in Swagger UI).

If `ACCESS_CODE` is not set, the gate is disabled (returns immediately) —
useful for local dev. In production set it via Railway Variables tab.

Comparison uses constant-time `hmac.compare_digest` to prevent timing attacks.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Query, Request, status


def require_access_code(
    request: Request,
    code: str | None = Query(
        default=None,
        description="รหัสเข้าใช้งาน — ถามจาก admin (อย่าเขียนใน code/repo)",
    ),
    x_access_code: str | None = Header(
        default=None,
        alias="X-Access-Code",
        description="ทางเลือก: ส่งผ่าน HTTP header แทน query param",
    ),
) -> None:
    """FastAPI dependency that rejects requests missing/with-wrong access code.

    Falls through silently if ACCESS_CODE is not configured (open mode).
    Accepts the code via either the `code` query param or the `X-Access-Code`
    header — whichever is present wins.
    """
    expected = request.app.state.cfg.access_code
    if not expected:
        return

    presented = code or x_access_code
    if not presented or not hmac.compare_digest(
        presented.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid access code. Send via query param "
                   "'?code=' or HTTP header 'X-Access-Code'.",
        )
