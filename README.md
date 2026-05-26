# Game Hit Ranking API

API ภาษา Python (FastAPI) ที่จัดอันดับ "เกมฮิต" จาก v2 casino game stream
บน Trino โดยรวมยอดทุก operator (global) ใช้ข้อมูล 30 วันล่าสุด
และอัพเดตอัตโนมัติวันละครั้ง (03:05 UTC = 10:05 ตามเวลาไทย)

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
ระหว่างนั้น `/health` ตอบ 200 (process รันอยู่) แต่ `/ready` จะตอบ 503
จนกว่า refresh จะเสร็จ — `/games/hits` ก็จะตอบ 503 ในช่วงนั้นเช่นกัน

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | ฟรี | Liveness — process ยังรันมั้ย (200 เสมอ ถ้า server ตอบ) |
| GET | `/ready` | ฟรี | Readiness — cache โหลดเสร็จหรือยัง (503 ตอน warmup) |
| GET | `/games/hits` | **ต้องมี code** | รายชื่อ provider เรียงตาม unique players พร้อมเกมยอดฮิตในแต่ละ provider |
| POST | `/refresh` | **ต้องมี token** | สั่ง refresh ทันที (ใช้ ~40 วินาที) |
| GET | `/docs` | ฟรี | Swagger UI — เทสยิงตรง browser ได้ |
| GET | `/redoc` | ฟรี | ReDoc UI ทางเลือก (อ่านง่ายกว่า แต่เทสไม่ได้) |
| GET | `/openapi.json` | ฟรี | OpenAPI 3 spec — import เข้า Postman/Insomnia ได้ |

### Authentication

มี security 2 ชั้นแยกกัน:

1. **`ACCESS_CODE`** — รหัสสำหรับ `/games/hits` (data endpoint). ส่งได้ 2 ทาง:
   - HTTP header: `X-Access-Code: 9998`
   - Query parameter: `?code=9998`
2. **`REFRESH_TOKEN`** — secret สำหรับ `POST /refresh` (operation endpoint). ส่งผ่าน:
   - HTTP header: `X-Refresh-Token: <token>`

ทั้งสองตัวเป็น env var — local dev ไม่ตั้งก็เปิดให้ทุกคนใช้ + log warning
production (Railway) บังคับให้ตั้ง ดู [SECURITY.md](SECURITY.md) สำหรับรายละเอียด

### Query params ของ `/games/hits`

- `provider_limit=10` — ส่งเฉพาะ Top N provider
- `games_per_provider=5` — เกมต่อ provider เอามาแค่ N ตัว
- `provider=PGS` — กรองเฉพาะ provider เดียว (ใส่รหัสเช่น `PGS`, `SAG`)
- `code=9998` — access code (ทางเลือกแทน header)

### ตัวอย่าง curl

```bash
URL=https://<your-app>.up.railway.app

# ใช้ header (recommended)
curl -H "X-Access-Code: 9998" "$URL/games/hits?provider_limit=10"

# หรือใช้ query param (เปิดในเบราว์เซอร์ได้)
curl "$URL/games/hits?provider_limit=10&code=9998"

# manual refresh (ต้องมี REFRESH_TOKEN)
curl -X POST -H "X-Refresh-Token: <token>" $URL/refresh
```

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
- `HIT_REFRESH_CRON_HOUR=3`, `HIT_REFRESH_CRON_MINUTE=5` — refresh วันละครั้งเวลา 03:05 UTC (เปลี่ยนเป็น `*` ถ้าอยากทุกชั่วโมง หรือ `*/6` ทุก 6 ชั่วโมง)
- `HIT_GAMES_PER_PROVIDER=50` — เก็บเกมต่อ provider ไว้ใน cache สูงสุดกี่ตัว (0 = ทั้งหมด)
- `HIT_CACHE_FILE=data/hits.json` — ที่เก็บ cache บนดิสก์ (โหลดต่อเนื่องเวลา restart)
- `ACCESS_CODE=` — รหัสเข้าใช้งาน `/games/hits` (เช่น `9998`) — ส่งผ่าน header `X-Access-Code` หรือ query `?code=` ถ้าไม่ตั้งจะเปิดให้ทุกคนเรียกได้
- `REFRESH_TOKEN=` — shared secret ป้องกัน `/refresh` (ดูใน [SECURITY.md](SECURITY.md))
- `CORS_ORIGINS=*` — รายชื่อ origin คั่นด้วย comma เช่น `https://app.example.com,https://staging.example.com` (default `*` ใช้ได้กับข้อมูล aggregate read-only)

## How it works

```
┌──────────────┐   refresh every     ┌────────────┐
│ APScheduler  ├──── 1 day (UTC) ───▶│  refresh   │
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

## Deploy บน Railway

Railway เหมาะที่สุด: free credit $5/เดือน, persistent process รองรับ scheduler,
auto-detect Python project, HTTPS public URL ฟรี

### ขั้นตอน (ครั้งแรก ~10 นาที)

1. **Push code ขึ้น GitHub** (ของจริง — Railway connect GitHub ง่ายสุด)
   ```powershell
   # สร้าง repo ใน GitHub ผ่าน UI หรือ:
   gh repo create gamehit-api --private --source=. --push
   # หรือ manual:
   git remote add origin https://github.com/<your-user>/gamehit-api.git
   git push -u origin main
   ```

2. **Create Railway project**
   - ไปที่ https://railway.app → New Project → Deploy from GitHub repo
   - เลือก repo `gamehit-api`
   - Railway detect Python อัตโนมัติ (ใช้ Nixpacks อ่าน `requirements.txt` + `Procfile`)

3. **ตั้ง Environment Variables** ใน Railway dashboard → Variables tab
   ```
   TRINO_HOST=<your-trino-host>            # ห้าม commit ค่าจริง
   TRINO_PORT=443
   TRINO_USER=<your-trino-user>
   TRINO_PASSWORD=<your-trino-password>
   TRINO_CATALOG=delta
   TRINO_HTTP_SCHEME=https
   ACCESS_CODE=9998                        # 4 หลัก หรือ string อะไรก็ได้
   REFRESH_TOKEN=<random-string-32-chars>  # บังคับตั้งสำหรับ production
   ```
   > 💡 `PORT` Railway ตั้งให้อัตโนมัติ ไม่ต้องเซ็ต
   > 🔐 ค่าใน Variables tab ถูก encrypt at-rest — ห้ามใส่ในไฟล์ commit เด็ดขาด
   > 🎲 generate refresh token: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   > 🔑 ACCESS_CODE คือรหัสที่ testers ต้องส่งมาในทุก request ไป `/games/hits`

4. **Generate Public Domain**: Settings → Networking → Generate Domain
   ได้ URL แบบ `https://gamehit-api-production.up.railway.app`

5. **เทสยิงดู** (deploy แรกใช้เวลา ~2 นาที + warmup 40 วิ)
   ```bash
   curl https://<your-url>.up.railway.app/health
   # เปิด /docs ในเบราว์เซอร์
   ```

### Healthcheck

`railway.json` ตั้งให้ Railway ดู `/health` ภายใน 120 วินาที — initial refresh
ใช้เวลา ~40 วินาที จึงผ่านสบาย ถ้า Trino ช้ามาก deploy จะ fail
(Railway จะ retry 5 ครั้งก่อนเลิกล้ม)

### ข้อควรระวัง

- **Single-instance only**: scheduler เป็น in-process — ถ้าเอาไป scale หลาย replica
  จะมีหลาย scheduler ยิง Trino พร้อมกัน (เปลือง). ถ้าจะ scale ต้องย้าย scheduler
  ออกไปเป็น Railway Cron job แยก
- **Ephemeral disk**: ไฟล์ `data/hits.json` จะหายเวลา redeploy — initial refresh
  จะเด้งใหม่อัตโนมัติ (~40 วินาที). ถ้าจะ persist จริง ต้องเพิ่ม Railway Volume
- **Cost**: idle ปกติ ~$0.01-0.02/ชั่วโมง = ~$5-15/เดือน (free credit คุ้ม)

## ทดสอบ API ผ่าน Swagger UI

หลัง deploy เปิด `https://<your-url>/docs` แล้ว:

1. **กดปุ่ม "Authorize" ที่มุมขวาบน** (ขึ้นเพราะมี `ACCESS_CODE` ตั้งใน env)
2. ใส่รหัส (`9998`) ในช่อง `APIKeyHeader` หรือ `APIKeyQuery` (อย่างใดอย่างหนึ่งก็พอ)
3. กด **Authorize** → **Close**
4. คลิก `GET /games/hits` → **Try it out** → ใส่ query params → **Execute**
5. Response เด้งขึ้นมาให้เลย พร้อม curl command สำเร็จรูปก๊อปไปใช้ต่อ

> 💡 `/docs` ของ FastAPI เป็น Swagger UI สำเร็จรูป — testers ไม่ต้อง install
> อะไรก็เทสยิงได้ครบทุก endpoint
> 🔑 ใส่รหัสครั้งเดียวพอ Swagger จะ remember ตลอด session

## Notes

- ใช้ตาราง `delta.default.v2_silver_precal_prod_stream` ตามที่ skill
  casino-trino แนะนำ — มี column `fullname_provider` ในตัวอยู่แล้ว
  ไม่ต้อง join master เพิ่ม
- `provider_fullname` ที่ตัว v2 stream เป็น `NULL` (มีอยู่บ้าง เช่น `1UP`, `AMG`)
  จะ fallback ไปใช้รหัส `provider` แทน เพื่อกัน UI พัง
- ขอบเขตเป็น **global** ทุก operator/prefix รวมกัน ถ้าจะตัดเฉพาะ prefix
  ต้องไป join v8 cus ดูตัวอย่างใน `~/.claude/skills/casino-trino/references/JOIN_V8_V2.md`
