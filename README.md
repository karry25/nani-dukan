# Nani Dukan (working name)

A helper for small shop owners in India. It does the boring daily work and never sends anything on its own: it only shows drafts and proposals, and you decide.

## What it does
- **Nightly check-in**: type one note in Hindi, English or Hinglish ("aaj sale 5200, kharcha 800, cash 6100, Anjali ne 300 diye"). It fills a small form. Nothing is saved until you confirm. Missing numbers are left blank, never guessed.
- **Udhaar (credit) book**: who owes what, with draft reminders you send yourself.
- **Bills inbox**: drop many bill photos or paste text. They are read, sorted by type, totalled, and duplicates or unreadable ones wait for your review.
- **Month-end close**: totals are added up by code. A checklist lists what is left (missing check-in days, bills to review, money to collect, stock to reorder). The AI only writes a short note, and a guard rejects any note that contains a number not in the totals.
- **Customer chats**: paste a customer message, get a draft reply with prices only from your catalog. Edit it, and the app may propose a rule ("free delivery above Rs 999"). A rule is saved only when you tap Keep.
- **While you sleep**: one screen that shows only what needs you (missing check-in, low or negative stock, money owed, bills to review, no stock check in 7 days).
- **Quick bill**: type or dictate one line ("Ramesh ko 10 SIM, 5 recharge card, paid 300"). Prices come from your catalog, the total is added by code, stock goes down and any unpaid part goes to udhaar, after one Confirm tap.
- **Stock check**: send a shelf photo; the AI counts, code compares with the ledger (match, short, extra, not seen). Counts are marked AI counts; nothing changes until you tick items to fix.
- **Rulebook and Activity**: see, delete and audit everything the helper learned or did.
- **Scam Shield** (plain code, no AI): checks payment CLAIMS in chats against your own udhaar book and flags mismatches ("says Rs 300 paid, book shows Rs 900 pending"), overpayment-cash-back trick, and pressure phrases ("SMS late aata hai", screenshot-as-proof, fake customer care); a scammer watchlist (name/phone/UPI) that pops up in red on any future chat; a QR check that catches QR-swap (your counter QR suddenly paying someone else's UPI ID) and the "scan to receive money" trick; and a one-tap evidence-pack PDF for police/bank complaints. It never accuses anyone - it only shows what your own records say.

## Run it
```
python3 server.py            # mock model, no key needed
LLM_API_KEY=... python3 server.py   # real model (BharatCode OpenAI-compatible endpoint)
python3 -m unittest          # 52 tests
python3 evals/run_evals.py   # 20 chat evals incl. 6 prompt-injection attacks
```
Python 3.10+, standard library only.

## Security
- Passwords: scrypt with per-user salt. Sessions: random token, only its hash is stored, HttpOnly SameSite=Strict cookie, CSRF header on every write.
- Every query filters on the signed-in user's id. Tests check that user B gets 404 or nothing on user A's data and files.
- The model key lives only on the server (environment variable). The browser never sees it.
- Untrusted text (customer messages, bills) is fenced and treated as data. Model output is validated to a fixed shape. Prices are checked against the catalog in code. Money maths is done in code, never by the model.
- No outbound sending anywhere in the code. Rules are saved only on an explicit tap.
- Limits: per-user and global daily AI call caps, login and sign-up throttles, body size cap, image magic-byte check, 2 MB upload cap.
- CSP, nosniff, frame-deny headers. UI renders all text with textContent.
- Delete account removes all data and uploaded files.

## Honest limits
- Tested with a rule-based mock model (52 unit tests pass; 17 of 20 chat evals pass on the mock - the 3 misses are mock word-matching limits, not security failures; all 6 injection attacks are blocked). Real-model quality (Hinglish, bill photos) is measured only when a key is set; run `evals/run_evals.py`.
- Scam Shield compares claims with YOUR book. It cannot see your bank account, and it cannot tell a fake screenshot from the image itself - nobody reliably can. The flag says "not confirmed in your records", never "fake".
- SQLite file storage: fine for a demo, back it up for real use. No HTTPS built in (put it behind a TLS proxy and set the Secure cookie flag).
- Nightly check-in is a form you open; there is no push reminder because the app never contacts anyone.
