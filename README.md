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
   - HTTP header: `X-Access-Code: <code>`
   - Query parameter: `?code=<code>`
2. **`REFRESH_TOKEN`** — secret สำหรับ `POST /refresh` (operation endpoint). ส่งผ่าน:
   - HTTP header: `X-Refresh-Token: <token>`

ทั้งสองตัวเป็น env var — local dev ไม่ตั้งก็เปิดให้ทุกคนใช้ + log warning
production (Railway) บังคับให้ตั้ง **ค่าจริงเก็บใน Railway Variables เท่านั้น
ห้าม commit หรือเขียนใน docs สาธารณะ** ดู [SECURITY.md](SECURITY.md) สำหรับรายละเอียด

### Query params ของ `/games/hits`

- `provider_limit=10` — ส่งเฉพาะ Top N provider
- `games_per_provider=5` — เกมต่อ provider เอามาแค่ N ตัว
- `provider=PGS` — กรองเฉพาะ provider เดียว (ใส่รหัสเช่น `PGS`, `SAG`)
- `code=<value>` — access code (ทางเลือกแทน header)

### ตัวอย่าง curl

```bash
URL=https://<your-app>.up.railway.app
CODE=<access-code-จาก-admin>
TOKEN=<refresh-token-จาก-admin>

# ใช้ header (recommended)
curl -H "X-Access-Code: $CODE" "$URL/games/hits?provider_limit=10"

# หรือใช้ query param (เปิดในเบราว์เซอร์ได้)
curl "$URL/games/hits?provider_limit=10&code=$CODE"

# manual refresh (ต้องมี REFRESH_TOKEN)
curl -X POST -H "X-Refresh-Token: $TOKEN" $URL/refresh
```

## Response shape

```json
{
  "refreshed_at": "2026-05-29T03:05:00+00:00",
  "window_days": 30,
  "metric": "unique_players",
  "scope": "global",
  "provider_count": 148,
  "providers": [
    {
      "rank": 1,
      "provider_code": "PGS",
      "provider_fullname": "Pgsoft Seamless",
      "unique_players": 8142412,
      "game_count": 164,
      "games": [
        { "rank": 1, "game_id": "60531c5534d88c344ce9acbd", "game_name": "treasures of aztec", "unique_players": 4041133 },
        { "rank": 2, "game_id": "60531c5534d88c344ce9acb2", "game_name": "mahjong ways 2",     "unique_players": 2465932 }
      ]
    }
  ]
}
```

Field reference:
- `provider_code` — รหัส provider (ใช้เป็น provider_id ได้เลย เช่น `PGS`, `SAG`)
- `provider_fullname` — ชื่อ provider แบบเต็มสำหรับ display
- `game_id` — รหัสเกมจาก warehouse (24-hex ObjectId สำหรับ slot games)
- `game_name` — ชื่อเกมสำหรับ display
- `unique_players` — จำนวนคนเล่นไม่ซ้ำใน 30 วัน (= metric ของอันดับ)

หมายเหตุ — การ map ด้วย `game_id`:
- **Slot games** (PGS, PMTS, JL, ...): `game_id` map 1:1 กับ `game_name` — ใช้ map ได้ตรง
- **Sport/Lottery** (Single Sport, Mix Parlay Step, AMBLOTTO): warehouse ใช้
  game_id ต่อ session (แต่ละ match/งวด) เรา **roll up รวมเป็น 1 row ต่อชื่อ**
  แล้วตั้ง `game_id: null` — `unique_players` นับรวมทุก session ของเกมนั้น
  (เช่น "football" 1 row = ผู้เล่นรวมทุกแมตช์ใน 30 วัน). ถ้า `game_id` เป็น
  null แปลว่าเป็นเกม session-based ให้ map ด้วย `(provider_code, game_name)` แทน

Cache เก็บ **ทุกเกม** ที่ provider มี (ไม่มี cap) — request ขอกี่เกมต่อ
provider ก็ได้ผ่าน `?games_per_provider=N` (เช่น PMTS มี 642 เกม)

หน้าเว็บ render เพียงวน `providers` (อันดับเรียงให้แล้ว) แต่ละ provider
แสดงชื่อด้วย `provider_fullname` แล้วโชว์ `games` ด้านล่างตามอันดับใน array.

## Config (`.env`)

ทุกค่ามี default ที่ใช้งานได้ ยกเว้น `TRINO_HOST` / `TRINO_USER` ที่ต้องตั้งเอง:

- `HIT_WINDOW_DAYS=30` — กี่วันย้อนหลัง (default หนึ่งเดือน)
- `HIT_REFRESH_CRON_HOUR=3`, `HIT_REFRESH_CRON_MINUTE=5` — refresh วันละครั้งเวลา 03:05 UTC (เปลี่ยนเป็น `*` ถ้าอยากทุกชั่วโมง หรือ `*/6` ทุก 6 ชั่วโมง)
- `HIT_CACHE_FILE=data/hits.json` — ที่เก็บ cache บนดิสก์ (โหลดต่อเนื่องเวลา restart)
- `ACCESS_CODE=` — รหัสเข้าใช้งาน `/games/hits` (ตั้งค่าจริงใน Railway Variables เท่านั้น) — ส่งผ่าน header `X-Access-Code` หรือ query `?code=` ถ้าไม่ตั้งจะเปิดให้ทุกคนเรียกได้
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
   ACCESS_CODE=<your-access-code>          # รหัสที่ tester ต้องส่งมา
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

1. คลิก `GET /games/hits`
2. **Try it out**
3. ใส่ค่าใน params:
   - `code` — รหัสที่ admin ให้มา (จำเป็น)
   - `provider_limit`, `games_per_provider`, `provider` — optional
4. **Execute** → response เด้งขึ้นมาให้เลย พร้อม curl command สำเร็จรูปก๊อปไปใช้ต่อ

> 💡 `/docs` ของ FastAPI เป็น Swagger UI สำเร็จรูป — testers ไม่ต้อง install
> อะไรก็เทสยิงได้ครบทุก endpoint
> 🔑 รหัสจะอยู่ใน URL ของ request (`?code=...`) — เห็นใน browser history
> ถ้ากังวลใช้ header `X-Access-Code` แทน (Swagger ให้เลือกได้ทั้งสองช่อง)

## Notes

- ใช้ตาราง `delta.default.v2_silver_precal_prod_stream` ตามที่ skill
  casino-trino แนะนำ — มี column `fullname_provider` ในตัวอยู่แล้ว
  ไม่ต้อง join master เพิ่ม
- `provider_fullname` ที่ตัว v2 stream เป็น `NULL` (มีอยู่บ้าง เช่น `1UP`, `AMG`)
  จะ fallback ไปใช้รหัส `provider` แทน เพื่อกัน UI พัง
- ขอบเขตเป็น **global** ทุก operator/prefix รวมกัน ถ้าจะตัดเฉพาะ prefix
  ต้องไป join v8 cus ดูตัวอย่างใน `~/.claude/skills/casino-trino/references/JOIN_V8_V2.md`
