"""Scam Shield: plain-code checks, no AI. The model never decides what is a scam;
code compares payment CLAIMS with the shop's own books and known scam patterns.
Nothing here sends, blocks or deletes anything: outputs are flags and advice cards."""
import re
from urllib.parse import parse_qs, urlparse

AMT = r"(\d[\d,]{0,8})"
CLAIM_WORDS = re.compile(
    r"(paid|payment|pay kar|kar diya|bhej diya|bhej raha|bheja hai|pais[ae] bhej|rupaye bhej|"
    r"sent you|transfer|jama|ho gaya|hogaya|diye|diya hai|received|upi me|gpay|phonepe|paytm)", re.I)
CASHBACK_WORDS = re.compile(
    r"(cash wapas|cash back|paise wapas|zyada|jyada|extra|zyada bhej|return kar|wapas kar|"
    r"change de|baaki cash|difference)", re.I)
PRESSURE = [
    (re.compile(r"(sms.{0,20}(late|nahi|slow)|message nahi aaya|aata hai sms)", re.I),
     "'SMS late aata hai' is the classic fake-payment excuse. The only truth is money in YOUR account."),
    (re.compile(r"(screenshot|screen shot|photo bhej|photo dikha)", re.I),
     "A screenshot is not proof. Fake 'payment successful' screens are the #1 shop scam. Check your own records first."),
    (re.compile(r"(customer care|helpline|support team|kyc|verify kar|otp|pin batao|pin number)", re.I),
     "No bank or app ever asks for OTP/PIN/KYC on chat. This looks like a fake customer-care trick."),
    (re.compile(r"(scan.{0,20}(receive|paane|lene)|receive.{0,20}scan|qr scan kar)", re.I),
     "Scanning a QR only SENDS money, it can never receive it. Anyone asking you to scan to receive is scamming you."),
]
UPI_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,49}@[a-zA-Z][a-zA-Z0-9]{1,20}$")
NAME_RE = re.compile(r"\b([A-Z][a-z]{2,29})\s+(?:ne|ka|ki|ko)\b")


def valid_upi(s):
    return bool(UPI_RE.fullmatch((s or "").strip()))


def _amounts(text):
    out = []
    for m in re.finditer(r"(?:rs\.?|₹|inr)?\s*" + AMT, text, re.I):
        v = int(m.group(1).replace(",", ""))
        if 1 <= v <= 10_000_000:
            out.append(v)
    return out


def extract_payment_claim(text):
    """Code-only read of one customer message. Returns names/amounts found and what kind of claim it is."""
    text = text or ""
    is_claim = bool(CLAIM_WORDS.search(text))
    names = [n for n in NAME_RE.findall(text) if n.lower() not in
             ("upi", "sms", "ok", "hello", "namaste", "please", "thanks")]
    amounts = _amounts(text)
    return {"is_claim": is_claim,
            "claimed": max(amounts) if is_claim and amounts else None,
            "names": names,
            "wants_cashback": bool(CASHBACK_WORDS.search(text)),
            "tips": [tip for pat, tip in PRESSURE if pat.search(text)]}


def claim_flags(claim, balances_by_name):
    """Compare a payment claim with the ledger. balances_by_name: lowercase name -> owed amount.
    Returns a list of human-readable flags (empty = nothing suspicious)."""
    flags = list(claim["tips"])
    if not claim["is_claim"]:
        return flags
    c = claim["claimed"]
    if claim["wants_cashback"]:
        flags.append("OVERPAYMENT TRICK: a real transfer 'by mistake' plus a cash-return request. "
                     "Never return cash for a digital overpayment - the original transfer can be reversed. "
                     "Ask them to take it back through the same app.")
    matched = [(n, balances_by_name[n.lower()]) for n in claim["names"]
               if n.lower() in balances_by_name]
    if c is None:
        flags.append("Payment claimed but no amount found. Confirm the exact amount in your own account before handing over goods.")
    elif matched:
        for name, owed in matched:
            if owed <= 0:
                flags.append(f"{name} says Rs {c} paid, but your book shows nothing pending for them. "
                             "Confirm it reached YOUR account before believing it.")
            elif c < owed:
                flags.append(f"{name} says Rs {c} paid; your book shows Rs {owed} pending. "
                             f"Short by Rs {owed - c}. Verify in your account, then update the book.")
            elif c > owed:
                flags.append(f"{name} says Rs {c} paid; your book shows only Rs {owed} pending. "
                             "Check whether the extra is a mistake before accepting it.")
    elif claim["names"]:
        flags.append("Payment claimed by " + ", ".join(claim["names"]) +
                     ", but they are not in your udhaar book. Confirm the money in YOUR account before handing over goods.")
    else:
        flags.append("Payment claimed. Confirm it shows in YOUR bank/UPI app - not on their screen - before goods leave the counter.")
    return flags


def parse_upi_qr(text):
    """Parse a scanned QR payload. Returns dict with ok, and for UPI intents: pa/pn/am."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "reason": "empty"}
    u = urlparse(text)
    if u.scheme.lower() != "upi" or u.netloc.lower() not in ("pay", ""):
        return {"ok": False, "reason": "not_upi"}
    q = parse_qs(u.query)
    pa = (q.get("pa") or [""])[0].strip()
    am = (q.get("am") or [""])[0].strip()
    out = {"ok": True, "pa": pa, "pn": (q.get("pn") or [""])[0].strip(), "am": None}
    try:
        out["am"] = int(round(float(am))) if am else None
    except ValueError:
        pass
    return out


def check_qr(text, own_upi="", expected_amount=None, purpose="verify_own"):
    """Verdict card for one scanned QR. purpose: verify_own (daily counter-QR check)
    or receive (someone asked the shopkeeper to scan this to 'receive' money)."""
    reasons, status = [], "ok"
    p = parse_upi_qr(text)
    if purpose == "receive":
        status = "danger"
        reasons.append("STOP. A QR code can only SEND money from your account - it can never receive money. "
                       "Anyone who asks you to scan a QR to receive a payment is scamming you.")
    if not p["ok"]:
        return {"status": "danger" if status == "danger" else "unknown",
                "reasons": reasons + ["This QR is not a UPI payment code. Do not scan unknown QRs."], "parsed": p}
    if not p["pa"] or not valid_upi(p["pa"]):
        status = "danger"
        reasons.append("This QR has no valid UPI ID. Do not pay it.")
    elif purpose == "verify_own":
        if not own_upi:
            status = "unknown"
            reasons.append("Add your shop's UPI ID first - without it I cannot tell whether this QR is really yours.")
        elif p["pa"].lower() == own_upi.lower():
            reasons.append(f"Good: this QR pays your own UPI ID ({own_upi}).")
        else:
            status = "danger"
            reasons.append(f"QR-SWAP ALERT: this QR pays {p['pa']}, not your UPI ID {own_upi}. "
                           "Someone may have pasted a fake sticker over your QR. Remove it and tell nearby shops.")
    if expected_amount is not None and p["am"] is not None and p["am"] != expected_amount:
        if status != "danger":
            status = "warn"
        reasons.append(f"Amount inside the QR is Rs {p['am']}, expected Rs {expected_amount}. Check before paying.")
    if not reasons:
        reasons.append("UPI QR to " + (p["pn"] or p["pa"]) + ". Check the name on your own screen before paying.")
    return {"status": status, "reasons": reasons, "parsed": p}
