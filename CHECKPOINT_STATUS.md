# Nani Dukan - Checkpoint Status

Format per gate: BUILD / TEST / EVIDENCE / STATUS / FIX. Readiness stages (never confused): prototype < functional MVP < tested MVP < staging-ready < beta-ready < production-ready < deployed < validated.

**Current stage: TESTED MVP** (works and passes its tests locally; not staged, not deployed, real AI model not yet measured).

| Gate | Status | Evidence | Fix / next |
|---|---|---|---|
| 00 Need | N/A | Hackathon entry; need documented in README (real nani's daily work, fake-payment scams) | - |
| 01 Architecture | PASS | Stdlib-only: server.py + service layer + swappable LLM client; deterministic code first, AI only for extraction/drafting | - |
| 02 Repo & supply chain | PASS | No dependencies, no secrets in repo (.env.example only), BharatCode.txt honest | Keep secrets scan on every push |
| 03 Core journey | PASS | check-in, udhaar, bills, month-end, quick bill, stock, chats, Scam Shield - all in tests/test_*.py | - |
| 04 Identity & authz | PASS | scrypt, session tokens (hash stored), CSRF header, per-user queries; isolation tests prove user B gets 404/nothing on A's data | - |
| 05 Data protection | PASS | Uploads per-user dir with random names; delete-account wipes rows + files (tested) | Backups for real use are owner-run (documented) |
| 06 App security | PASS | CSP/nosniff/frame-deny, body caps, image magic bytes, login/signup throttles, textContent rendering; tests in test_server.py | TLS via proxy documented, not built in |
| 07 AI safety | PARTIAL | Fenced untrusted text, JSON shape validation, catalog-price guard, no rule without a tap, 6/6 injection evals blocked; AI call caps per user/day | Run evals on the REAL model once a key exists (blocked: no API access) |
| 08 Resilience | PASS | LLMError -> 503 with generic message; mock fallback; DB schema upgrades in place (tested via existing-DB migration path) | - |
| 09 Performance & cost | PARTIAL | Call caps (150/user/day, 2500 global) bound cost; no load test done | Load test before any public deployment |
| 10 UX & accessibility | PASS | Phone layout, big buttons, Hinglish copy, drafts-only flow | - |
| 11 Observability | PARTIAL | Activity log (every action, per user) in-app; usage counters | No server-side metrics/alerts (single-process demo) |
| 12 Staging / release rehearsal | NOT TESTED | Never deployed | Needs her yes for any hosting/deploy step |
| 13 Private beta | N/A | Not launched | After staging |
| 14 Go / no-go | N/A | Not launched | After beta |
| 15 Post-launch | N/A | Not launched | - |

## Scam Shield checkpoint (this update)
- BUILD: payment-claim flags vs ledger, overpayment-trick warning, pressure-phrase tips, scammer watchlist (name/phone/UPI) with repeat alerts, QR-swap + scan-to-receive QR checks with daily reminder, evidence-pack PDF per customer, UPI ID in shop settings.
- TEST: 24 new tests (tests/test_scam.py) - QR verdicts, claim-vs-ledger flags, watchlist isolation, digest reminders, PDF contents, HTTP auth/CSRF/isolation.
- EVIDENCE: `python3 -m unittest` 52/52 OK; `evals/run_evals.py` 17/20 (3 pre-existing mock misses, 6/6 attacks blocked); PDF verified by pdftotext.
- STATUS: PASS (on mock model; Scam Shield itself uses no AI).
- FIX: none open for Scam Shield. Real-model eval still blocked on BharatCode API access.

## Known honest gaps (not hidden)
- AI features run on a rule-based MOCK until a BharatCode key exists (free student route needs account verification; account onboarding unfinished).
- Bill-photo and shelf-photo reading are wired but UNVERIFIED against BharatCode's image format.
- No load test, no deployment, no monitoring beyond the in-app activity log.
