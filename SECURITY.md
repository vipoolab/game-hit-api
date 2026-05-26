# Security Notes

เอกสารนี้สรุปว่าอะไรปลอดภัย/ไม่ปลอดภัยที่จะ expose
และวิธีตรวจสอบหลัง deploy

## What is safe to expose publicly

| Item | Why it's safe |
|---|---|
| `/games/hits` response | Aggregate counts ระดับ provider/game — ไม่มี username, IP, PII |
| `/health` | แค่ timestamp + provider count — ไม่บอกอะไรเกี่ยวกับลูกค้า |
| `/docs`, `/redoc`, `/openapi.json` | ข้อมูล schema ของ API — ไม่ leak credentials |
| `provider_fullname`, `game_name` | ชื่อที่ vendor ตั้งเอง — ไม่ใช่ข้อมูลลูกค้า |

## What MUST stay in env (never commit)

```
TRINO_HOST          ← hostname ของ data warehouse internal
TRINO_USER          ← service account
TRINO_PASSWORD      ← service account password
REFRESH_TOKEN       ← shared secret สำหรับ POST /refresh
```

ในไฟล์ที่ commit ลง git ต้องเป็น placeholder ทั้งหมด
(เช็ค `.env.example` เป็นตัวอย่าง)

## What CANNOT leak from this app

**(verified ใน [`app/refresh.py`](app/refresh.py) และ [`app/trino_client.py`](app/trino_client.py))**

1. **Cache file (`data/hits.json`)** — มีแค่: `provider_code`, `provider_fullname`,
   `game_name`, `unique_players` (int), `spins` (int), `bet_volume` (float).
   ไม่มี: username, IP, country, bank, transaction, prefix-level breakdown,
   หรือชื่อจริงของผู้เล่น
2. **Application logs** — log แค่ SQL 120 ตัวอักษรแรก (ไม่มี credentials เลย)
   และ error type (ไม่มี stack trace + ไม่มี hostname เพราะถูก strip แล้ว
   ใน `_sanitize_error()` ของ trino_client)
3. **API error responses** — แค่ `Refresh failed — see server logs`
   (รายละเอียดจริงๆ อยู่ใน server log เท่านั้น) hostname ถูกลบออกก่อนส่งต่อ

## Hardening checklist สำหรับ production deploy

ก่อน push ลง Railway/cloud:

### 1. Git ไม่มี secrets

```bash
# จะต้องไม่เจออะไร
git ls-files | xargs grep -l -E "(real-host|real-user|real-password)"

# .env ต้องไม่อยู่ใน tracked files
git ls-files | grep -E "^\.env$"          # ต้องไม่มี output

# data/ ต้องถูก ignore
git check-ignore data/hits.json           # ต้องเจอ pattern
```

### 2. Railway Variables ตั้งครบ

ใน Railway → Project → Variables tab ต้องมี:
- [ ] `TRINO_HOST`
- [ ] `TRINO_USER`
- [ ] `TRINO_PASSWORD`
- [ ] `REFRESH_TOKEN` (สำคัญ! ถ้าไม่ตั้ง endpoint `/refresh` จะ disabled อัตโนมัติ)

Generate token:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 3. ทดสอบหลัง deploy

```bash
URL=https://<your-app>.up.railway.app

# 1. health endpoint ใช้งานได้
curl -s $URL/health
# expect: {"status":"ok",...}

# 2. /docs โหลด (Swagger UI)
curl -s -o /dev/null -w "%{http_code}\n" $URL/docs
# expect: 200

# 3. /refresh ถูกปฏิเสธโดยไม่มี token
curl -s -o /dev/null -w "%{http_code}\n" -X POST $URL/refresh
# expect: 401

# 4. /refresh ถูกปฏิเสธด้วย token ผิด
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "X-Refresh-Token: wrong" $URL/refresh
# expect: 401

# 5. response ไม่ leak hostname
curl -s $URL/games/hits?provider_limit=1 | grep -c "sparq-qd\|trino\.\|aptd5"
# expect: 0
```

### 4. Logs ไม่ leak

ไปดูที่ Railway → Deployments → Logs:
- ต้องไม่เห็น `TRINO_PASSWORD=...` หรือ token จริง
- SQL logs ต้องถูก truncate ที่ 120 chars
- ไม่ควรเห็น `Authorization: Basic ...` header

ถ้าเห็น = แสดงว่ามีคน push log statement ใหม่ที่ leak — แก้ทันที

## Threat model

### In scope (เราป้องกัน)

- **Credential leak via git** — `.gitignore` + manual scrub of README
- **Credential leak via response** — `_sanitize_error()` strips host from
  bubbled exceptions
- **Credential leak via logs** — trino library uses DEBUG level for auth
  headers, our log level is INFO
- **Brute-force on REFRESH_TOKEN** — `hmac.compare_digest()` (constant-time)
- **Refresh abuse (cost)** — token required in cloud env, lock prevents
  concurrent refresh
- **SQL injection** — only int-cast user input touches SQL

### Out of scope (ต้องมีระบบอื่นช่วย)

- **Public IP discovery** — anyone hitting your Railway URL can identify it
  as a FastAPI service. ใช้ Cloudflare proxy ถ้าต้องการซ่อน
- **DDoS / abuse on GET endpoints** — ไม่มี rate limit ใส่ใน app นี้
  (ใช้ Railway/Cloudflare WAF เพิ่ม)
- **Data warehouse access control** — service account ของเราต้องมีสิทธิ์อ่าน
  เฉพาะ `delta.default.v2_silver_precal_prod_stream` table ที่จำเป็น —
  ตั้งใน Trino role/permission ไม่ใช่ที่ app นี้
- **Network egress filter** — app นี้เปิด HTTPS ไปยัง Trino host —
  ถ้า host เปลี่ยน เช่นโดน DNS poisoning, app จะเชื่อมไป host ใหม่
  (verify=True ช่วยกัน TLS MITM ได้ แต่ไม่กัน DNS rebinding)

## ถ้าหลุดแล้ว

ถ้า `TRINO_PASSWORD` หรือ `REFRESH_TOKEN` รั่ว:

1. **เปลี่ยน password ทันที** — แจ้ง data engineering ให้ rotate service account
2. **อัพเดต Railway Variables** — ใส่ค่าใหม่ → trigger redeploy
3. **Review git history** — ดูว่ารั่วผ่าน commit ไหน
   ```bash
   git log --all --full-history -p | grep -E "(password|token)"
   ```
4. **ถ้า commit แล้ว push แล้ว** — ลบ commit ไม่ช่วย (GitHub cache)
   ต้องถือว่า secret หลุดแล้ว rotate เท่านั้น
5. **Audit Trino query logs** — ดูว่ามี query ที่ผิดปกติจาก IP/user agent
   ที่เราไม่รู้จักหรือเปล่า
