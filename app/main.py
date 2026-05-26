"""FastAPI app — serves cached hit-games ranking and exposes a manual refresh."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from .cache import HitsCache
from .config import load_config
from .refresh import refresh_once
from .scheduler import start_scheduler
from .schemas import HealthResponse, HitsResponse, RefreshResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gamehit")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    cache = HitsCache(cfg.cache_file)
    cache.load_from_disk()

    scheduler = start_scheduler(cfg, cache)

    if cache.get() is None:
        def _initial_refresh():
            try:
                refresh_once(cfg, cache)
            except Exception:
                log.exception("Initial refresh failed — API will serve 503 until next run")
        threading.Thread(target=_initial_refresh, daemon=True).start()

    app.state.cfg = cfg
    app.state.cache = cache
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


API_DESCRIPTION = """
API จัดอันดับ **เกมฮิต** จากข้อมูล v2 casino game stream ย้อนหลัง 30 วัน
รวมทุก operator (global) อัพเดตอัตโนมัติทุก 1 ชั่วโมง

## วิธีใช้

1. เรียก `GET /games/hits` เพื่อดึงรายชื่อ provider เรียงตามอันดับ
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Refreshed-At"],
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
    summary="เช็คสถานะ API + เวลาที่ refresh ล่าสุด",
)
def health(response: Response) -> dict[str, Any]:
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
    responses={
        503: {"description": "Cache ยังไม่พร้อม (กำลังโหลดข้อมูลครั้งแรก) — ลองใหม่อีกครั้งใน 30-60 วินาที"}
    },
)
def get_hits(
    provider_limit: int | None = Query(
        None, ge=1, le=200,
        description="คืน Top N provider เท่านั้น (default: ทั้งหมด)",
        examples=[10],
    ),
    games_per_provider: int | None = Query(
        None, ge=0, le=200,
        description="คืนเกมต่อ provider แค่ N ตัว (default: ตามค่า cache, ปกติ 50)",
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
    responses={401: {"description": "Invalid refresh token (เมื่อตั้ง REFRESH_TOKEN ไว้)"}},
)
def manual_refresh(
    x_refresh_token: str | None = Header(
        default=None,
        alias="X-Refresh-Token",
        description="ใส่ token ตามที่ตั้งใน env `REFRESH_TOKEN` (ถ้าตั้ง — ไม่ตั้งก็เปิดใช้ฟรี)",
    ),
):
    """รัน refresh ตอนนี้เลย ไม่รอตาราง cron.

    ใช้เวลา ~40 วินาที (2 queries) — response จะกลับเมื่อ cache update เสร็จ.
    """
    cfg = app.state.cfg
    if cfg.refresh_token:
        if x_refresh_token != cfg.refresh_token:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
    payload = refresh_once(cfg, _cache(app))
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
