# Game Hit Ranking API

API ภาษา Python (FastAPI) ที่จัดอันดับ "เกมฮิต" จาก v2 casino game stream
บน Trino โดยรวมยอดทุก operator (global) ใช้ข้อมูล 30 วันล่าสุด
และอัพเดตอัตโนมัติทุก 1 ชั่วโมง

จัดอันดับด้วย **unique players** (จำนวนคนเล่นไม่ซ้ำ) ทั้งระดับ provider
และระดับเกมภายในแต่ละ provider พร้อมส่งคืน `provider_fullname` ที่อ่านง่าย
(เช่น `Pgsoft Seamless` แทนที่จะเป็น `PGS`).

## Quick start

```powershell
# 1. ลง dependencies
python -m pip install -r requirements.txt

# 2. คัดลอก config แล้วใส่ credentials จริง
copy .env.example .env
notepad .env   # เติม TRINO_HOST / TRINO_USER / TRINO_PASSWORD

# 3. รัน server
python run.py
```

ครั้งแรกที่รัน server จะ refresh cache ครั้งแรกใน background (~40 วินาที)
ก่อนหน้านั้น `/games/hits` จะส่ง 503 และ `/health` ส่ง `status: warming_up`

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | สถานะ cache + เวลาที่ refresh ล่าสุด |
| GET | `/games/hits` | รายชื่อ provider เรียงตาม unique players พร้อมเกมยอดฮิตในแต่ละ provider |
| POST | `/refresh` | สั่ง refresh ทันที (ใส่ header `X-Refresh-Token` ถ้าตั้ง `REFRESH_TOKEN` ไว้) |
| GET | `/docs` | Swagger UI อัตโนมัติของ FastAPI |

### Query params ของ `/games/hits`

- `provider_limit=10` — ส่งเฉพาะ Top N provider
- `games_per_provider=5` — เกมต่อ provider เอามาแค่ N ตัว
- `provider=PGS` — กรองเฉพาะ provider เดียว (ใส่รหัสเช่น `PGS`, `SAG`)

## Response shape

```json
{
  "refreshed_at": "2026-05-26T10:05:00+00:00",
  "window_days": 30,
  "metric": "unique_players",
  "scope": "global",
  "provider_count": 138,
  "providers": [
    {
      "rank": 1,
      "provider_code": "PGS",
      "provider_fullname": "Pgsoft Seamless",
      "unique_players": 8152810,
      "spins": 523133866,
      "bet_volume": 137300213959.92,
      "game_count": 50,
      "games": [
        {
          "rank": 1,
          "game_name": "treasures of aztec",
          "unique_players": 1234567,
          "spins": 21745484,
          "bet_volume": 6691622.50
        }
      ]
    }
  ]
}
```

หน้าเว็บ render เพียงวน `providers` (อันดับเรียงให้แล้ว) แต่ละ provider
แสดงชื่อด้วย `provider_fullname` แล้วโชว์ `games` ด้านล่างตามอันดับใน array.

## Config (`.env`)

ทุกค่ามี default ที่ใช้งานได้ ยกเว้น `TRINO_HOST` / `TRINO_USER` ที่ต้องตั้งเอง:

- `HIT_WINDOW_DAYS=30` — กี่วันย้อนหลัง (default หนึ่งเดือน)
- `HIT_REFRESH_CRON_HOUR=*`, `HIT_REFRESH_CRON_MINUTE=5` — refresh ทุกชั่วโมงตอนนาทีที่ 5
- `HIT_GAMES_PER_PROVIDER=50` — เก็บเกมต่อ provider ไว้ใน cache สูงสุดกี่ตัว (0 = ทั้งหมด)
- `HIT_CACHE_FILE=data/hits.json` — ที่เก็บ cache บนดิสก์ (โหลดต่อเนื่องเวลา restart)
- `REFRESH_TOKEN=` — ถ้าตั้งจะต้องใส่ header `X-Refresh-Token` ตอน POST /refresh

## How it works

```
┌──────────────┐   refresh every     ┌────────────┐
│ APScheduler  ├───── 1 hour ───────▶│  refresh   │
│ (in-process) │                     │  function  │
└──────────────┘                     └─────┬──────┘
                                           │ 2 queries (~40s)
                                           ▼
                                  ┌─────────────────┐
                                  │ v2_silver_precal│
                                  │ _prod_stream    │
                                  │ (Trino)         │
                                  └────────┬────────┘
                                           │ provider + game rollup
                                           ▼
                                  ┌─────────────────┐
                                  │ HitsCache       │
                                  │ (memory + JSON) │
                                  └────────┬────────┘
                                           │
                                  ┌────────▼────────┐
                                  │ GET /games/hits │
                                  │  (instant)      │
                                  └─────────────────┘
```

- 2 queries แยกกัน: หนึ่งตัวรวมระดับ provider (unique players ที่นับถูก)
  อีกตัวรวมระดับ (provider, game). รวมประมาณ 40 วินาทีต่อ refresh.
- Cache เก็บใน memory + persist เป็น JSON ที่ `data/hits.json` —
  เวลา restart โหลดต่อจากไฟล์ได้ทันที (ไม่ต้องรอ refresh แรก)
- API ตอบจาก memory ทันที (1-2 ms) — Trino โหลดไม่ถูกชนทุก request

## Notes

- ใช้ตาราง `delta.default.v2_silver_precal_prod_stream` ตามที่ skill
  casino-trino แนะนำ — มี column `fullname_provider` ในตัวอยู่แล้ว
  ไม่ต้อง join master เพิ่ม.
- `provider_fullname` ที่ตัว v2 stream เป็น `NULL` (มีอยู่บ้าง เช่น `1UP`, `AMG`)
  จะ fallback ไปใช้รหัส `provider` แทน เพื่อกัน UI พัง.
- ขอบเขตเป็น **global** ทุก operator/prefix รวมกัน ถ้าจะตัดเฉพาะ prefix
  ต้องไป join v8 cus ดูตัวอย่างใน `~/.claude/skills/casino-trino/references/JOIN_V8_V2.md`.
