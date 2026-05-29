"""FastAPI app — serves cached hit-games ranking and exposes a manual refresh."""
from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from .cache import HitsCache
from .config import load_config
from .refresh import refresh_once
from .scheduler import start_scheduler
from .schemas import HealthResponse, HitsResponse, RefreshResponse
from .security import require_access_code

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gamehit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()

    # Production safety: REFRESH_TOKEN must be set when not running locally.
    # We detect "production" via the common cloud env vars set by Railway/Heroku.
    is_cloud = any(os.environ.get(k) for k in ("RAILWAY_ENVIRONMENT", "DYNO", "FLY_APP_NAME"))
    if is_cloud and not cfg.refresh_token:
        log.warning(
            "SECURITY: REFRESH_TOKEN is not set while running in a cloud env "
            "(RAILWAY_ENVIRONMENT/DYNO detected). POST /refresh is publicly "
            "triggerable — anyone can run an expensive Trino query. "
            "Set REFRESH_TOKEN in the Variables tab."
        )
    if not cfg.refresh_token:
        log.warning("REFRESH_TOKEN not set — POST /refresh is open. OK for local dev.")
    if not cfg.access_code:
        log.warning("ACCESS_CODE not set — /games/hits is open to anyone. OK for local dev.")
    else:
        log.info("ACCESS_CODE gate enabled on /games/hits (%d chars)", len(cfg.access_code))

    cache = HitsCache(cfg.cache_file)
    cache.load_from_disk()

    scheduler = start_scheduler(cfg, cache)

    if cache.get() is None:
        def _initial_refresh():
            try:
                refresh_once(cfg, cache)
            except Exception:
                # Log type only, not full stack — avoids leaking SQL/host
                # in production logs (the full trace is still in DEBUG level).
                log.error("Initial refresh failed — API will serve 503 until next run", exc_info=False)
                log.debug("Initial refresh full traceback:", exc_info=True)
        threading.Thread(target=_initial_refresh, daemon=True).start()

    app.state.cfg = cfg
    app.state.cache = cache
    app.state.scheduler = scheduler
    app.state.refresh_in_progress = threading.Lock()

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


API_DESCRIPTION = """
API จัดอันดับ **เกมฮิต** จากข้อมูล v2 casino game stream ย้อนหลัง 30 วัน
รวมทุก operator (global) อัพเดตอัตโนมัติวันละครั้ง

## 🔑 Authentication

`GET /games/hits` ต้องส่ง **access code** มาด้วย (รับจาก admin ผ่านช่องทาง private)
ส่งได้ 2 ทาง:
- Query parameter: `?code=<your-code>` ← โผล่ใน Swagger UI ตรง params ของ endpoint
- HTTP header: `X-Access-Code: <your-code>` ← ทางเลือกสำหรับ programmatic calls

**ใน Swagger UI**: เปิด `/games/hits` → **Try it out** → ใส่รหัสในช่อง `code` →
**Execute** ครับ ง่ายๆ แค่นั้น

`POST /refresh` ต้องใช้ token แยกอีกตัว (`X-Refresh-Token` header)

## วิธีใช้

1. เรียก `GET /games/hits` พร้อม access code → ดึงรายชื่อ provider เรียงตามอันดับ
   พร้อมเกมยอดฮิตในแต่ละ provider
2. ใช้ query param `?provider_limit=10` / `?games_per_provider=5` /
   `?provider=PGS` เพื่อจำกัด/กรองข้อมูล
3. ในเเต่ละ object ของ provider ให้อ่าน `provider_fullname` (ชื่อเต็ม)
   ส่วน `games[]` เรียงตามอันดับให้แล้ว — โชว์ตามลำดับใน array ได้เลย

## Metric

จัดอันดับด้วย **unique players** (จำนวนคนเล่นไม่ซ้ำ) เป็นตัววัด
เพราะสะท้อนความนิยมในวงกว้าง — ไม่ถูก distort โดย whale auto-bet
"""


app = FastAPI(
    title="Game Hit Ranking API",
    description=API_DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    contact={"name": "Casino BI Team"},
    openapi_tags=[
        {"name": "hits", "description": "ดึงอันดับเกมฮิต"},
        {"name": "ops", "description": "ดูสถานะ + สั่ง refresh"},
    ],
)

# CORS: GET endpoints (read-only aggregated data) are safe to expose globally.
# /refresh is protected by REFRESH_TOKEN — even with allow_origins=* a cross-site
# attacker would still need the token, which is in a custom header that requires
# CORS preflight. Override via CORS_ORIGINS env to lock down further.
_cors_origins_env = os.environ.get("CORS_ORIGINS", "*").strip()
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Refresh-Token"],
    expose_headers=["X-Refreshed-At"],
    max_age=3600,
)


def _cache(app: FastAPI) -> HitsCache:
    return app.state.cache


def _filtered_payload(
    payload: dict[str, Any],
    *,
    provider_limit: int | None,
    games_per_provider: int | None,
    provider_code: str | None,
) -> dict[str, Any]:
    providers = payload["providers"]

    if provider_code:
        providers = [p for p in providers if p["provider_code"].upper() == provider_code.upper()]

    if provider_limit is not None and provider_limit > 0:
        providers = providers[:provider_limit]

    if games_per_provider is not None and games_per_provider >= 0:
        providers = [
            {**p, "games": p["games"][:games_per_provider], "game_count": min(games_per_provider, p["game_count"])}
            for p in providers
        ]

    return {
        **payload,
        "provider_count": len(providers),
        "providers": providers,
    }


@app.get(
    "/health",
    tags=["ops"],
    response_model=HealthResponse,
    summary="Liveness check — process ยังอยู่มั้ย (always 200 ถ้า server ยังรันอยู่)",
)
def health() -> dict[str, Any]:
    """Liveness probe สำหรับ Railway/K8s/load balancer.

    คืน 200 ถ้า process ยังตอบสนอง — ไม่ผูกกับ cache เพราะ refresh ตัวแรก
    ใช้เวลา ~40s. ถ้าอยากเช็คว่าข้อมูลพร้อมหรือยัง ดู `/ready`
    """
    payload = _cache(app).get()
    if payload is None:
        return {"status": "warming_up", "refreshed_at": None,
                "provider_count": None, "window_days": None}
    return {
        "status": "ok",
        "refreshed_at": payload["refreshed_at"],
        "provider_count": payload["provider_count"],
        "window_days": payload["window_days"],
    }


@app.get(
    "/ready",
    tags=["ops"],
    response_model=HealthResponse,
    summary="Readiness check — cache โหลดเสร็จหรือยัง (503 = ยังไม่พร้อม)",
)
def ready(response: Response) -> dict[str, Any]:
    """Readiness probe — บอกว่า API พร้อมตอบ `/games/hits` แล้วหรือยัง.

    - 200 = cache มีแล้ว, ยิงได้
    - 503 = ยังโหลดข้อมูลครั้งแรกอยู่ (รอ ~40 วินาที) หรือ Trino เรียกไม่ติด
    """
    payload = _cache(app).get()
    if payload is None:
        response.status_code = 503
        return {"status": "warming_up", "refreshed_at": None,
                "provider_count": None, "window_days": None}
    return {
        "status": "ok",
        "refreshed_at": payload["refreshed_at"],
        "provider_count": payload["provider_count"],
        "window_days": payload["window_days"],
    }


@app.get(
    "/games/hits",
    tags=["hits"],
    response_model=HitsResponse,
    summary="รายชื่อ provider เรียงตามอันดับ + เกมยอดฮิตในแต่ละ provider",
    dependencies=[Depends(require_access_code)],
    responses={
        401: {"description": "ไม่ได้ส่งรหัส / รหัสผิด — ใส่ header `X-Access-Code` หรือ `?code=`"},
        503: {"description": "Cache ยังไม่พร้อม (กำลังโหลดข้อมูลครั้งแรก) — ลองใหม่อีกครั้งใน 30-60 วินาที"},
    },
)
def get_hits(
    provider_limit: int | None = Query(
        None, ge=1, le=200,
        description="คืน Top N provider เท่านั้น (default: ทั้งหมด)",
        examples=[10],
    ),
    games_per_provider: int | None = Query(
        None, ge=0, le=2000,
        description="คืนเกมต่อ provider แค่ N ตัว (default: ทั้งหมดที่อยู่ใน cache)",
        examples=[5],
    ),
    provider: str | None = Query(
        None,
        description="กรองเฉพาะ provider เดียว (ใส่รหัสเช่น PGS, SAG — case-insensitive)",
        examples=["PGS"],
    ),
):
    """ดึงรายชื่อ **provider เรียงตาม unique players** ใน 30 วันล่าสุด
    พร้อม **เกมยอดฮิตในแต่ละ provider** (เรียงตามอันดับเช่นกัน).

    Response ใส่เวลาที่ refresh ล่าสุดมาให้ใน `refreshed_at` (UTC) —
    หน้าเว็บใช้ตรวจว่าเข้ามาเอาข้อมูลใหม่หรือยัง
    """
    payload = _cache(app).get()
    if payload is None:
        raise HTTPException(status_code=503, detail="Cache warming up — try again shortly")
    return _filtered_payload(
        payload,
        provider_limit=provider_limit,
        games_per_provider=games_per_provider,
        provider_code=provider,
    )


@app.post(
    "/refresh",
    tags=["ops"],
    response_model=RefreshResponse,
    summary="สั่ง refresh ข้อมูลทันที (ใช้เวลา ~40 วินาที)",
    responses={
        401: {"description": "Invalid refresh token"},
        409: {"description": "Refresh already in progress"},
        503: {"description": "Refresh disabled (REFRESH_TOKEN not configured in cloud env)"},
    },
)
def manual_refresh(
    request: Request,
    x_refresh_token: str | None = Header(
        default=None,
        alias="X-Refresh-Token",
        description="ใส่ token ตามที่ตั้งใน env `REFRESH_TOKEN` — บังคับใน production",
    ),
):
    """รัน refresh ตอนนี้เลย ไม่รอตาราง cron.

    ใช้เวลา ~40 วินาที (2 queries) — response จะกลับเมื่อ cache update เสร็จ.

    **Security**:
    - ใน cloud env (Railway/Heroku/Fly) ต้องตั้ง `REFRESH_TOKEN` ไม่งั้น endpoint
      จะ disable เพื่อกัน abuse — query 1 ครั้ง = Trino คิวพร้อมเงิน
    - token comparison ใช้ constant-time เพื่อกัน timing attack
    - มี lock กัน concurrent refresh ซ้อน — request ที่ 2 จะได้ 409
    """
    cfg = app.state.cfg

    is_cloud = any(os.environ.get(k) for k in ("RAILWAY_ENVIRONMENT", "DYNO", "FLY_APP_NAME"))
    if is_cloud and not cfg.refresh_token:
        raise HTTPException(
            status_code=503,
            detail="Refresh endpoint disabled: REFRESH_TOKEN must be configured "
                   "when running in a cloud environment",
        )

    if cfg.refresh_token:
        if not x_refresh_token or not hmac.compare_digest(
            x_refresh_token.encode("utf-8"),
            cfg.refresh_token.encode("utf-8"),
        ):
            raise HTTPException(status_code=401, detail="Invalid refresh token")

    lock: threading.Lock = request.app.state.refresh_in_progress
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Refresh already in progress")
    try:
        payload = refresh_once(cfg, _cache(app))
    except Exception:
        log.error("Manual refresh failed", exc_info=False)
        log.debug("Manual refresh full traceback:", exc_info=True)
        raise HTTPException(status_code=502, detail="Refresh failed — see server logs")
    finally:
        lock.release()
    return {
        "status": "refreshed",
        "refreshed_at": payload["refreshed_at"],
        "provider_count": payload["provider_count"],
    }


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {
        "name": "Game Hit Ranking API",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "hits": "/games/hits",
    }
