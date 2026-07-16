# Schatten Brutality — Text Preset

> **FULL VULN CHECKLIST** — ini yang harus di-test tiap target (biar gak ada yang kelewat pas "gas full"):

```
┌─ AUTH & SESSION ────────────────────────────────┐
│ □ Open signup (Firebase/Supabase REST)          │
│ □ Weak password policy / no rate limit          │
│ □ JWT none-alg / weak secret (jwt-forge.py)    │
│ □ Session fixation / token reuse               │
│ □ Role tampering (POST role:admin)            │
│ □ IDOR (ganti user_id / order_id di param)    │
│ □ Privilege escalation user→admin             │
│ □ Account takeover via email/UUID mismatch     │
└───────────────────────────────────────────────┘

┌─ INJECTION & LOGIC ────────────────────────────┐
│ □ SQLi (error-based, blind, time-based)       │
│ □ NoSQLi ($ne, $regex, $gt) (noqli.py)      │
│ □ XSS (stored, reflected, DOM)               │
│ □ Prototype pollution (__proto__ writable)     │
│ □ dangerouslySetInnerHTML sinks                │
│ □ eval() / Function() / setTimeout(string)     │
│ □ Race condition / TOCTOU (race-test.py)      │
│ □ Business logic (negative qty, double redeem) │
│ □ Mass assignment (extra params di JSON)       │
└───────────────────────────────────────────────┘

┌─ TRANSPORT & CONFIG ────────────────────────────┐
│ □ Open redirect (?redirect=//evil.com)         │
│ □ SSRF (/api/proxy?url=http://169.254.169.254)│
│ □ XXE (upload XML, parse external)            │
│ □ Path traversal (../../etc/passwd)           │
│ □ File upload (svg/xss, polyglot)            │
│ □ CORS misconfig (Access-Control-Allow-Origin:*)│
│ □ Security headers (CSP, HSTS, X-Frame)      │
│ □ Exposed .env / .git / backup files          │
│ □ API keys di client JS / window globals       │
│ □ Source map (.js.map) leak                  │
└───────────────────────────────────────────────┘

┌─ ACCESS CONTROL ────────────────────────────────┐
│ □ Admin routes client-side only guard          │
│ □ Middleware bypass (x-middleware-subrequest) │
│ □ Hidden endpoints (fuzz /api/*, /admin/*)   │
│ □ GraphQL introspection enabled               │
│ □ CVE-2025-29927 (Next.js middleware)       │
│ □ Server actions callable directly             │
│ □ Rate limit absence (bruteforce)             │
│ □ Enumeration (user list, invoice IDs)        │
└───────────────────────────────────────────────┘

┌─ 3RD PARTY & SUPPLY CHAIN ─────────────────────┐
│ □ Firebase/Supabase/Clerk config exposed      │
│ □ Webhook no signature verify (HMAC)          │
│ □ Payment tampering (amount override)         │
│ □ Domain dash trap (xy.com ≠ x-y.com)        │
│ □ Subdomain takeover (parked/unused DNS)      │
│ □ CDN / edge cache stale (x-vercel-cache:HIT)│
└───────────────────────────────────────────────┘
```

> Checklist ini yang bikin audit "meaty" — gak cuma 4 findings kayak phantom tadi.
> Tiap item: test → bukti (response code / payload) → report. Yang clean tetep dilaporin (⚪ CLEAN) biar keliatan gak skip.

---

## PRINSIP

1. **Recon dulu, nembak kemudian.** Klasifikasi target (static vs dynamic) sebelum deep dive.
2. **Classify cepat:** `curl -I` → `server: Netlify` + gak ada `Set-Cookie` + gak ada `/_next/` = STATIC. Stop, lapor, pindah.
3. **Static site = dead end.** Gak ada server = gak ada attack surface. Jangan fuzz 50 path buang waktu.
4. **AI-generated ≠ AI-powered.** Landing page template (AOS + Swup + Feather) ≠ backend AI yang jalan.
5. **Domain dash trap:** `x-y.com` ≠ `xy.com`. Verify DNS + SSL SAN + redirect target sebelum assume pemilik sama.
6. **Placeholder = celah bisnis.** Grep `placeholder`, `your_`, `TODO`, `example.com` sebelum anggap production-ready.
7. **Gap technical ≠ gap bisnis.** User bayar → gak bisa konfirmasi = chargeback risk. Lapor dua-duanya.

---

## WORKFLOW (5 PHASE)

```
┌─ PHASE 1: RECON TRIAGE ─────────────────────────────┐
│ curl -I <target>          → server type, headers     │
│ dig <target>              → DNS, IP, CNAME           │
│ grep api|fetch|endpoint    → ada backend?             │
│ Classify: STATIC → STOP / DYNAMIC → LANJUT           │
└──────────────────────────────────────────────────────┘

┌─ PHASE 2: SURFACE MAPPING (dynamic only) ────────────┐
│ Download JS chunks → grep endpoint /api/*            │
│ Cari auth flow (Firebase/Supabase/Clerk/JWT)         │
│ Cari admin routes di JS bundle                       │
│ Cari config exposed (API key, project ID)            │
│ Cari dangerouslySetInnerHTML / eval sinks            │
└──────────────────────────────────────────────────────┘

┌─ PHASE 3: AUTH BYPASS ───────────────────────────────┐
│ Test signup open (Firebase REST: signUp)             │
│ Test session creation (/api/auth/session)            │
│ Test role tampering (POST role:admin)                │
│ Test middleware bypass (x-middleware-subrequest)     │
│ Test JWT forge (jwt-forge.py)                         │
└──────────────────────────────────────────────────────┘

┌─ PHASE 4: PRIVILEGE + LOGIC ─────────────────────────┐
│ Akses /admin/* dengan user biasa                     │
│ Cek client-side vs server-side authz                 │
│ Test IDOR (ganti user_id di param)                   │
│ Test race condition (race-test.py)                   │
│ Test NoSQLi (noqli.py)                                │
│ Prototype pollution: {}.__proto__.x = 1              │
└──────────────────────────────────────────────────────┘

┌─ PHASE 5: REPORT + PUSH ─────────────────────────────┐
│ Compile findings (CRITICAL/HIGH/MEDIUM/LOW/INFO)     │
│ Generate report → /tmp/<target>-audit/README.md      │
│ git init → gh repo create → push                     │
│ Log learnings → .learnings/LEARNINGS.md → GitHub     │
└──────────────────────────────────────────────────────┘
```

---

## TOOLS (skills/brutal-schatt/tools/)

| Tool | Fungsi |
|------|--------|
| `schatten-run.py` | Orchestrator: jalanin semua phase, watchdog timeout, progress incremental |
| `browser-harvest.py` | Headless browser: render page, cari sinks, prototype pollution check |
| `jwt-forge.py` | JWT tampering: none alg, weak secret, role claim |
| `noqli.py` | NoSQL injection: `$ne`, `$regex`, `$gt` payloads |
| `race-test.py` | Race condition: concurrent requests, TOCTOU |
| `lab_mock.py` | Mock target buat test toolchain sebelum live |

---

## FINDINGS FORMAT

```
🔴 CRITICAL: [count] → [what, impact]
🟡 MEDIUM:   [count] → [what]
🟢 LOW:      [count] → [what]
⚪ CLEAN:    [tested, not vuln]
```

Setiap finding: **Severity | Finding | Evidence | Impact | Fix**

---

## KNOWN PATTERNS (from past audits)

### appverse.id (2026-07-16)
- 🔴 Firebase open signup (no email verify)
- 🟡 Admin pages client-side authz only (`/admin/*` return 200 ke user)
- 🟡 Prototype pollution confirmed
- 🟡 dangerouslySetInnerHTML (2 sinks)
- ❌ CVE-2025-29927 patched, role tampering gak lolos

### astintech.id (2026-07-13)
- 🔴 API keys plaintext di DB
- 🔴 Open redirect `?redirect=`
- 🟡 No rate limit auth
- 🟡 Clerk publishable key di window

### phantom-intelligence.com (2026-07-16)
- 🟡 Telegram bot placeholder (`t.me/your_telegram_bot`)
- 🟡 Static QRIS (`qris_placeholder.png`)
- 🟢 HugeDomains parking leak (phantomintelligence.com dijual)
- ⚪ STATIC SITE — no backend exposed

---

## ANTI-PATTERNS (jangan lakuin)

- ❌ Fuzz 50 path di static site (buang waktu)
- ❌ Assume domain mirip = pemilik sama
- ❌ Skip `curl -I` classification
- ❌ Lapor "clean" tanpa test (bukti: response code)
- ❌ Gak push ke GitHub (semua hasil di repo)

---

## RULES

1. **Bukti atau diam.** Gak ada test = gak ada claim.
2. **Push ke GitHub.** Repo: `Cael1107/<target>-audit`.
3. **Log learnings.** Setiap audit → `.learnings/LEARNINGS.md` → push.
4. **Schatten Dual-Mode:** Brutal = full attack; Bug Hunt = security only.
5. **Fail-forward:** Tool gagal → alternatif (curl vs urllib vs browser).
6. **Visibility:** Status update tiap phase, jangan silent run.
