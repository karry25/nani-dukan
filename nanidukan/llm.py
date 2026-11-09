"""Swappable model clients. Agents only use LLMClient.complete().

OpenAICompatClient: any OpenAI-style /chat/completions endpoint. Default is BharatCode
(https://bharatcode.ai/api/model/v1, model qwen-3.8-27b). Key comes from the environment only.
MockClient: rule-based stand-in for tests and DEMO MODE. It is NOT an AI model; its output
must never be presented as model quality.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class LLMClient:
    name = "base"
    is_mock = False

    def complete(self, system, user, max_tokens=700, images=None):
        raise NotImplementedError


class OpenAICompatClient(LLMClient):
    def __init__(self, api_key, base_url=None, model=None, retries=2, timeout=60):
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://bharatcode.ai/api/model/v1")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "qwen-3.8-27b")
        self.retries, self.timeout = retries, timeout
        self.name = f"{self.model}"

    def complete(self, system, user, max_tokens=700, images=None):
        content = user
        if images:  # data URLs. UNVERIFIED against BharatCode's image format.
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": u}} for u in images]
        body = json.dumps({"model": self.model,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                           "max_tokens": max_tokens, "temperature": 0.2, "reasoning_effort": "none"}).encode()
        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.base_url + "/chat/completions", data=body, method="POST",
                                         headers={"Authorization": "Bearer " + self.api_key,
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                ch = data["choices"][0]
                if ch.get("finish_reason") == "length":
                    raise LLMError("output cut off")
                return ch["message"]["content"] or ""
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError, LLMError) as e:
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"model call failed: {type(last).__name__}")  # never echo key or body


def _sec(text, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1).strip() if m else ""


def _num(s):
    s = s.replace(",", "").strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k)?", s)
    if not m:
        return None
    v = float(m.group(1)) * (1000 if m.group(2) else 1)
    return int(v)


NUM = r"(\d[\d,]*(?:\.\d+)?k?)"
STOP = {"cash", "sale", "sales", "kharcha", "expense", "expenses", "aaj", "kal", "today", "stock", "ne", "ko",
        "udhaar", "udhar", "baaki", "credit", "rs", "rupees", "the", "and", "aur", "hai", "ka", "ki", "ke"}


class MockClient(LLMClient):
    name = "mock (rule-based stand-in, not an AI model)"
    is_mock = True

    def complete(self, system, user, max_tokens=700, images=None):
        t = re.search(r"TASK:(\w+)", system)
        t = t.group(1) if t else ""
        fn = getattr(self, "t_" + t, None)
        if not fn:
            raise LLMError("mock: unknown task")
        out = fn(user, images)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

    def _pairs(self, c):
        out = []
        for m in re.finditer(r"(\d+)\s*(?:x\s*)?([A-Za-z][A-Za-z ]{1,30}?)(?=,|\.| aur | and |$| ko | paid| diye)", c):
            out.append({"name": m.group(2).strip(), "qty": int(m.group(1))})
        if not out:
            for m in re.finditer(r"([A-Za-z][A-Za-z ]{1,30}?)\s*[:=-]?\s*(\d+)", c):
                out.append({"name": m.group(1).strip(), "qty": int(m.group(2))})
        return out

    def t_count(self, user, images):
        n = _sec(user, "note")
        if images and not n:
            return {"items": [], "readable": False}
        return {"items": self._pairs(n), "readable": True}

    def t_sale(self, user, images):
        c = _sec(user, "line")
        cust = re.match(r"\s*([A-Z][a-z]+)\s+ko\b", c)
        paid = re.search(r"(?:paid|diye|received)\s*(\d+)|(\d+)\s*(?:paid|diye)", c)
        body = re.sub(r"^\s*[A-Z][a-z]+\s+ko\s+", "", c)
        body = re.sub(r"(,|\s)*(paid|diye|received)\s*\d+.*$", "", body)
        return {"customer": cust.group(1) if cust else None, "items": self._pairs(body),
                "paid": int(paid.group(1) or paid.group(2)) if paid else None}

    # --- chat helper tasks
    def t_triage(self, user, images):
        c = _sec(user, "chat").lower()
        cat, urg = "price_enquiry", 2
        if re.search(r"\b(win|lottery|click this link|free gift|crypto|loan offer|investment)\b", c):
            cat, urg = "spam", 0
        elif re.search(r"(refund|damaged|broken|wrong item|not received|cheat|complain|kharab|toot)", c):
            cat, urg = "complaint", 3
        elif re.search(r"(order|buy|book|confirm|pay|upi|address|pin ?code|deliver|chahiye|lena hai|bhej)", c):
            cat, urg = "serious_buyer", 3
        elif re.search(r"(return policy|timing|kab tak|open|shipping charge|cod)", c):
            cat, urg = "repeat_question", 1
        return {"category": cat, "urgency": urg}

    def t_reply(self, user, images):
        cat_, rules, chat = _sec(user, "catalog"), _sec(user, "rules").lower(), _sec(user, "chat")
        tags = _sec(user, "tags")
        greet = "Hi!"
        if "bhaiya" in rules and re.search(r"\b(bhaiya|bhai|sir)\b", chat.lower()):
            greet = "Hi bhaiya!"
        lines = [greet]
        hit = None
        for ln in cat_.splitlines():
            m = re.match(r"\s*-\s*(.+?)\s*:\s*Rs\.?\s*(\d+)", ln)
            if m and m.group(1).lower() in chat.lower():
                hit = (m.group(1), m.group(2))
                break
        if "complaint" in tags:
            lines.append("I'm sorry about this. Please send a photo and your order number and I will sort it out.")
        elif hit:
            lines.append(f"{hit[0]} is Rs {hit[1]}.")
            if "pin code" in rules:
                lines.append("Please share your pin code and I will confirm delivery time.")
            elif "serious_buyer" in tags:
                lines.append("Share your address and I will confirm the order.")
        else:
            lines.append("Thanks for writing. Let me check and get back to you shortly.")
        return "\n".join(lines)

    def t_rule(self, user, images):
        b, a = _sec(user, "draft").lower(), _sec(user, "final").lower()
        if "pin code" in a and "pin code" not in b:
            return {"rule": "Ask for the buyer's pin code before quoting delivery.", "confidence": 0.7}
        if "bhaiya" in a and "bhaiya" not in b:
            return {"rule": "Greet male buyers with 'bhaiya'.", "confidence": 0.6}
        if "discount" in b and "discount" not in a:
            return {"rule": "Do not offer a discount in the first reply.", "confidence": 0.7}
        return {"rule": "", "confidence": 0.0}

    def t_nudge(self, user, images):
        name, amt = _sec(user, "name"), _sec(user, "amount")
        return f"Namaste {name}, a gentle reminder about the Rs {amt} pending at the shop. Whenever convenient. Thank you!"

    # --- nightly check-in
    def t_checkin(self, user, images):
        text = _sec(user, "checkin")
        out = {"cash": None, "sales": None, "expenses": None, "udhaar_given": [], "udhaar_received": [], "low_stock": [], "notes": ""}
        low = text.lower()
        for key, pat in (("cash", r"(?:cash|galla)[^\d]{0,15}" + NUM), ("sales", r"(?:sale|sales|bikri|becha)[^\d]{0,15}" + NUM),
                         ("expenses", r"(?:kharcha|kharch|expense|expenses)[^\d]{0,15}" + NUM)):
            m = re.search(pat, low)
            if m:
                out[key] = _num(m.group(1))
        for cl in re.split(r"[,.;\n]|\band\b|\baur\b", text):
            lc = cl.lower()
            nums = re.findall(NUM, lc)
            names = [w for w in re.findall(r"\b[A-Z][a-z]{2,}\b", cl) if w.lower() not in STOP]
            if names and nums and re.search(r"(udhaar|udhar|baaki|credit)", lc) and not re.search(r"(diye|diya paisa|wapas|jama|paid|chukaya|returned|de gaye|dediya)", lc):
                out["udhaar_given"].append({"name": names[0], "amount": _num(nums[-1])})
            elif names and nums and re.search(r"(diye|wapas|jama|paid|chukaya|returned|de gaye|dediya|payment)", lc):
                out["udhaar_received"].append({"name": names[0], "amount": _num(nums[-1])})
            elif re.search(r"(khatam|kam hai|low|finish|out of stock|nahi hai|khalas)", lc):
                words = [w for w in re.findall(r"[A-Za-z]+", lc) if w not in STOP and w not in ("khatam", "kam", "low", "finish", "out", "nahi", "khalas", "of")]
                if words:
                    out["low_stock"].append(words[0])
        return out

    # --- bills
    def t_bill(self, user, images):
        if images and not _sec(user, "bill"):
            return {"vendor": None, "date": None, "amount": None, "category": "other", "readable": False}
        t = _sec(user, "bill")
        first = next((ln.strip() for ln in t.splitlines() if ln.strip()), "")
        m = re.search(r"(?:grand total|total|amount|amt)[^\d]{0,15}" + NUM, t.lower())
        amt = _num(m.group(1)) if m else None
        d = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", t)
        date = None
        if d:
            dd, mm, yy = int(d.group(1)), int(d.group(2)), int(d.group(3))
            yy = yy + 2000 if yy < 100 else yy
            if 1 <= dd <= 31 and 1 <= mm <= 12:
                date = f"{yy:04d}-{mm:02d}-{dd:02d}"
        low = t.lower()
        cat = "stock_purchase"
        for k, words in (("electricity", ("electricity", "mseb", "bijli")), ("rent", ("rent", "kiraya")),
                         ("transport", ("transport", "freight", "tempo")), ("salary", ("salary", "wages")),
                         ("packaging", ("packaging", "carry bag", "bags"))):
            if any(w in low for w in words):
                cat = k
        return {"vendor": first[:60] or None, "date": date, "amount": amt, "category": cat, "readable": True}

    # --- month-end summary
    def t_summary(self, user, images):
        tot = json.loads(_sec(user, "totals") or "{}")
        return (f"This month you recorded sales of Rs {tot.get('sales', 0)} and expenses of Rs {tot.get('expenses', 0)}. "
                f"Bills total Rs {tot.get('bills_total', 0)}. Customers still owe you Rs {tot.get('udhaar_outstanding', 0)}. "
                f"You checked in on {tot.get('checkin_days', 0)} of {tot.get('days_in_month', 0)} days.")


def client_from_env():
    key = os.environ.get("LLM_API_KEY") or os.environ.get("BHARATCODE_API_KEY")
    return OpenAICompatClient(key, os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_MODEL")) if key else MockClient()
