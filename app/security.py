"""Access-code gate for data endpoints.

A simple shared-secret gate driven by `ACCESS_CODE` env var. Accepts the
code via either:
- HTTP header `X-Access-Code: <code>`
- query parameter `?code=<code>`

If `ACCESS_CODE` is not set, the gate is disabled (returns immediately) —
useful for local dev. In production set it via Railway Variables tab.

Comparison uses constant-time `hmac.compare_digest` to prevent timing attacks.

Swagger UI integration: registers an APIKeyHeader security scheme so testers
see an "Authorize" button at the top of /docs and can enter the code once.
"""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery

_HEADER_NAME = "X-Access-Code"
_QUERY_NAME = "code"

# auto_error=False so the missing-credentials branch can be combined across
# both header and query — FastAPI will not 403 on its own.
_header_scheme = APIKeyHeader(
    name=_HEADER_NAME,
    auto_error=False,
    description=f"รหัสเข้าใช้งาน (4 หลัก) ที่ตั้งใน env `ACCESS_CODE`",
)
_query_scheme = APIKeyQuery(
    name=_QUERY_NAME,
    auto_error=False,
    description=f"รหัสเข้าใช้งาน — ส่งผ่าน header `{_HEADER_NAME}` หรือ `?{_QUERY_NAME}=` ก็ได้",
)


def require_access_code(
    request: Request,
    header_value: str | None = Security(_header_scheme),
    query_value: str | None = Security(_query_scheme),
) -> None:
    """FastAPI dependency that rejects requests missing/with-wrong access code.

    Falls through silently if ACCESS_CODE is not configured (open mode).
    """
    expected = request.app.state.cfg.access_code
    if not expected:
        return

    presented = header_value or query_value
    if not presented or not hmac.compare_digest(
        presented.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing or invalid access code. Send via header "
                   f"'{_HEADER_NAME}' or query param '?{_QUERY_NAME}='.",
        )
