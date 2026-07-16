# Schatten Brutality — Text Preset

> Mode: **Obrak-abrik target web hasil buatan AI / production app.**
> Trigger: `brutal mode` / `schatten brutal` / `gas full` / `jebol ini`
> Author: Exilio 🧠 | Updated: 2026-07-16

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
