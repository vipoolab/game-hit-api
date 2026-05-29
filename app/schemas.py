"""Pydantic response models — used by FastAPI to render JSON schemas
and example payloads in the auto-generated /docs page.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class GameItem(BaseModel):
    rank: int = Field(..., description="อันดับของเกมภายใน provider นี้ (1 = ฮิตสุด)")
    game_id: str | None = Field(
        None,
        description="รหัสเกมจาก warehouse (24-hex ObjectId). Slot games map 1:1 "
                    "กับชื่อเกมจึงมี id เสมอ. Sport/lottery (เช่น football, หวย) "
                    "ใช้ id ต่อ session — เรารวมเป็น 1 row ต่อชื่อแล้วตั้ง game_id "
                    "เป็น null (ไม่มี id เดียวที่ stable)",
    )
    game_name: str = Field(..., description="ชื่อเกม (ตามที่ provider ตั้งมา)")
    unique_players: int = Field(..., description="จำนวนคนเล่นไม่ซ้ำใน 30 วัน")


class ProviderItem(BaseModel):
    rank: int = Field(..., description="อันดับ provider (1 = ฮิตสุด)")
    provider_code: str = Field(..., description="รหัส provider เช่น PGS, SAG")
    provider_fullname: str = Field(
        ...,
        description="ชื่อเต็มของ provider เช่น 'Pgsoft Seamless', 'SA Gaming' "
                    "— ถ้า warehouse ไม่มีชื่อเต็ม จะ fallback เป็นรหัส",
    )
    unique_players: int = Field(..., description="จำนวนคนเล่นไม่ซ้ำของ provider นี้ใน 30 วัน")
    game_count: int = Field(..., description="จำนวนเกมใน list นี้")
    games: list[GameItem] = Field(..., description="รายชื่อเกมเรียงตาม unique players (ฮิตสุดมาก่อน)")


class HitsResponse(BaseModel):
    refreshed_at: str = Field(..., description="เวลาที่ refresh cache ล่าสุด (UTC ISO-8601)")
    window_days: int = Field(..., description="ใช้ข้อมูลย้อนหลังกี่วัน")
    metric: str = Field(..., description="metric ที่ใช้จัดอันดับ (เช่น unique_players)")
    scope: str = Field(..., description="ขอบเขตข้อมูล (global / company / brand)")
    provider_count: int = Field(..., description="จำนวน provider ใน response")
    providers: list[ProviderItem] = Field(..., description="รายชื่อ provider เรียงตามอันดับ")

    model_config = {
        "json_schema_extra": {
            "example": {
                "refreshed_at": "2026-05-26T08:22:05.486442+00:00",
                "window_days": 30,
                "metric": "unique_players",
                "scope": "global",
                "provider_count": 2,
                "providers": [
                    {
                        "rank": 1,
                        "provider_code": "PGS",
                        "provider_fullname": "Pgsoft Seamless",
                        "unique_players": 8152810,
                        "game_count": 3,
                        "games": [
                            {"rank": 1, "game_id": "60531c5534d88c344ce9acbd", "game_name": "treasures of aztec", "unique_players": 4043719},
                            {"rank": 2, "game_id": "60531c5534d88c344ce9acb2", "game_name": "mahjong ways 2",     "unique_players": 2467466},
                            {"rank": 3, "game_id": "60531c5534d88c344ce9acc4", "game_name": "lucky neko",         "unique_players": 2146311},
                        ],
                    },
                    {
                        "rank": 19,
                        "provider_code": "SAG",
                        "provider_fullname": "SA Gaming",
                        "unique_players": 267226,
                        "game_count": 2,
                        "games": [
                            {"rank": 1, "game_id": "5fa1c3...", "game_name": "baccarat",  "unique_players": 250307},
                            {"rank": 2, "game_id": "5fa1c4...", "game_name": "thai hilo", "unique_players": 13505},
                        ],
                    },
                ],
            }
        }
    }


class HealthResponse(BaseModel):
    status: str = Field(..., description="ok | warming_up")
    refreshed_at: str | None = Field(None, description="เวลาที่ refresh ล่าสุด (null ถ้ายังไม่เคย)")
    provider_count: int | None = None
    window_days: int | None = None


class RefreshResponse(BaseModel):
    status: str = Field(..., description="refreshed")
    refreshed_at: str
    provider_count: int
