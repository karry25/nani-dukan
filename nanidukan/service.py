import json
"""All app logic. Every method takes user_id from the verified session and every query
filters on it. Nothing here sends anything to anyone: outputs are drafts and proposals."""
import base64
import calendar
import datetime as dt
import os
import re
import time

from . import agents
from .db import DB, jdump, jload
from .llm import LLMError
from .security import (RateLimiter, clean_text, hash_password, new_token, sniff_image, token_digest,
                       valid_password, valid_username, verify_password, MAX_CHAT)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SESSION_SECS = 7 * 24 * 3600


class AppError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def today():
    return dt.datetime.now(IST).date()


class Service:
    def __init__(self, db: DB, llm, upload_dir="data/uploads", user_cap=150, demo_cap=20, global_cap=2500, now=None):
        self.db, self.llm = db, llm
        self.upload_dir = upload_dir
        self.user_cap, self.demo_cap, self.global_cap = user_cap, demo_cap, global_cap
        self.rl = RateLimiter()
        self.today = now or today

    # ---------- auth
    def register(self, username, password, shop_name, ip="?"):
        if not self.rl.allow(("reg", ip), 10, 3600):
            raise AppError("Too many sign-ups from here. Try later.", 429)
        username = (username or "").strip()
        if not valid_username(username):
            raise AppError("Username: 3-32 letters, numbers, . _ -")
        if not valid_password(password):
            raise AppError("Password must be 8 to 128 characters")
        if self.db.one("SELECT id FROM users WHERE username=?", (username.lower(),)):
            raise AppError("That username is taken")
        salt, h = hash_password(password)
        uid = self.db.x("INSERT INTO users(username,salt,pw,created) VALUES(?,?,?,?)",
                        (username.lower(), salt, h, self.today().isoformat()))
        self.db.x("INSERT INTO shops(user_id,name) VALUES(?,?)", (uid, clean_text(shop_name or "My shop", 60) or "My shop"))
        return self._session(uid)

    def login(self, username, password, ip="?"):
        key = ("login", ip, (username or "").lower())
        if not self.rl.allow(key, 5, 900):
            raise AppError("Too many tries. Wait 15 minutes.", 429)
        u = self.db.one("SELECT * FROM users WHERE username=?", ((username or "").strip().lower(),))
        ok = verify_password(password or "", u["salt"], u["pw"]) if u else (hash_password("x") and False)
        if not ok:
            raise AppError("Wrong username or password", 401)
        self.rl.clear(key)
        return self._session(u["id"])

    def _session(self, uid):
        tok, csrf = new_token(), new_token()
        self.db.x("INSERT INTO sessions(token,user_id,csrf,expires) VALUES(?,?,?,?)",
                  (token_digest(tok), uid, csrf, time.time() + SESSION_SECS))
        return {"token": tok, "csrf": csrf, "user_id": uid}

    def auth(self, token):
        if not token:
            return None
        s = self.db.one("SELECT * FROM sessions WHERE token=? AND expires>?", (token_digest(token), time.time()))
        if not s:
            return None
        u = self.db.one("SELECT id,username FROM users WHERE id=?", (s["user_id"],))
        return {"user_id": u["id"], "username": u["username"], "csrf": s["csrf"]} if u else None

    def logout(self, token):
        self.db.x("DELETE FROM sessions WHERE token=?", (token_digest(token),))

    def delete_account(self, uid):
        for t in ("chats", "rules", "catalog", "ledger", "daily", "bills", "activity", "usage", "sessions", "customers", "shops", "stock_moves", "sales"):
            self.db.x(f"DELETE FROM {t} WHERE user_id=?", (uid,))
        self.db.x("DELETE FROM users WHERE id=?", (uid,))
        d = os.path.join(self.upload_dir, str(uid))
        if os.path.isdir(d):
            for f in os.listdir(d):
                os.remove(os.path.join(d, f))
            os.rmdir(d)

    # ---------- caps and log
    def _charge(self, uid):
        day = self.today().isoformat()
        g = self.db.one("SELECT calls FROM global_usage WHERE day=?", (day,))
        if g and g["calls"] >= self.global_cap:
            raise AppError("The app has reached today's free limit. Try tomorrow.", 429)
        u = self.db.one("SELECT username FROM users WHERE id=?", (uid,))
        cap = self.demo_cap if u and u["username"].startswith("demo-") else self.user_cap
        r = self.db.one("SELECT calls FROM usage WHERE user_id=? AND day=?", (uid, day))
        if r and r["calls"] >= cap:
            raise AppError("Today's limit for your shop is reached. Try tomorrow.", 429)
        self.db.x("INSERT INTO usage(user_id,day,calls) VALUES(?,?,1) ON CONFLICT(user_id,day) DO UPDATE SET calls=calls+1", (uid, day))
        self.db.x("INSERT INTO global_usage(day,calls) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1", (day,))

    def usage(self, uid):
        r = self.db.one("SELECT calls FROM usage WHERE user_id=? AND day=?", (uid, self.today().isoformat()))
        return {"used": r["calls"] if r else 0, "cap": self.user_cap}

    def log(self, uid, actor, action, detail=""):
        self.db.x("INSERT INTO activity(user_id,ts,actor,action,detail) VALUES(?,?,?,?,?)",
                  (uid, dt.datetime.now(IST).isoformat(timespec="seconds"), actor, action, clean_text(detail, 200)))

    def _ai(self, uid, fn, *a, **k):
        self._charge(uid)
        try:
            return fn(self.llm, *a, **k)
        except LLMError:
            raise AppError("The AI model is busy or unavailable. Please try again.", 503)

    # ---------- shop, catalog, rules
    def shop(self, uid):
        return self.db.one("SELECT name,language,policy FROM shops WHERE user_id=?", (uid,))

    def set_shop(self, uid, name, language, policy):
        self.db.x("UPDATE shops SET name=?,language=?,policy=? WHERE user_id=?",
                  (clean_text(name, 60) or "My shop", clean_text(language, 20) or "hinglish", clean_text(policy, 600), uid))

    def catalog(self, uid):
        return self.db.q("SELECT id,name,price FROM catalog WHERE user_id=? ORDER BY name", (uid,))

    def add_item(self, uid, name, price):
        name = clean_text(name, 60)
        try:
            price = int(price)
        except (TypeError, ValueError):
            raise AppError("Price must be a whole number")
        if not name or not (0 < price <= 1_000_000):
            raise AppError("Give an item name and a price")
        return self.db.x("INSERT INTO catalog(user_id,name,price) VALUES(?,?,?)", (uid, name, price))

    def del_item(self, uid, iid):
        self.db.x("DELETE FROM catalog WHERE id=? AND user_id=?", (iid, uid))

    def rules(self, uid):
        return self.db.q("SELECT id,text,source,uses,created FROM rules WHERE user_id=? ORDER BY id DESC", (uid,))

    def del_rule(self, uid, rid):
        self.db.x("DELETE FROM rules WHERE id=? AND user_id=?", (rid, uid))
        self.log(uid, "you", "deleted rule", str(rid))

    # ---------- chats
    def add_chat(self, uid, text):
        text = clean_text(text, MAX_CHAT)
        if not text:
            raise AppError("Paste a customer message first")
        tags = self._ai(uid, agents.triage, text)
        cat, rules, pol = self.catalog(uid), self.rules(uid), self.shop(uid)["policy"]
        draft = "" if tags["category"] == "spam" else self._ai(uid, agents.reply, text, tags, cat, rules, pol)
        flags = agents.check_draft(draft, cat) if draft else []
        cid = self.db.x("INSERT INTO chats(user_id,text,category,urgency,draft,flags,created) VALUES(?,?,?,?,?,?,?)",
                        (uid, text, tags["category"], tags["urgency"], draft, jdump(flags), self.today().isoformat()))
        for r in rules:
            if r["text"] and draft:
                self.db.x("UPDATE rules SET uses=uses+1 WHERE id=? AND user_id=?", (r["id"], uid))
        self.log(uid, "agents", "drafted reply", f"chat {cid} as {tags['category']}")
        return self.chat(uid, cid)

    def chat(self, uid, cid):
        c = self.db.one("SELECT * FROM chats WHERE id=? AND user_id=?", (cid, uid))
        if not c:
            raise AppError("Not found", 404)
        c["flags"] = jload(c["flags"], [])
        c["pending_rule"] = c["pending_rule"] or None
        return c

    def chats(self, uid):
        rows = self.db.q("SELECT id FROM chats WHERE user_id=? ORDER BY id DESC LIMIT 100", (uid,))
        return [self.chat(uid, r["id"]) for r in rows]

    def submit_edit(self, uid, cid, final):
        c = self.chat(uid, cid)
        final = clean_text(final, 1200)
        if not final:
            raise AppError("Write the reply you actually sent")
        rule = agents.propose_rule(self.llm, c["draft"], final) if final != c["draft"] and self._can_charge(uid) else None
        if rule:
            self._charge(uid)
        self.db.x("UPDATE chats SET final=?,pending_rule=?,status='done' WHERE id=? AND user_id=?", (final, rule, cid, uid))
        self.log(uid, "you", "edited a draft", f"chat {cid}")
        return self.chat(uid, cid)

    def _can_charge(self, uid):
        try:
            self._charge_check(uid)
            return True
        except AppError:
            return False

    def _charge_check(self, uid):
        day = self.today().isoformat()
        r = self.db.one("SELECT calls FROM usage WHERE user_id=? AND day=?", (uid, day))
        if r and r["calls"] >= self.user_cap:
            raise AppError("cap", 429)

    def decide_rule(self, uid, cid, keep):
        c = self.chat(uid, cid)
        if not c["pending_rule"]:
            raise AppError("No rule waiting")
        if keep:
            self.db.x("INSERT INTO rules(user_id,text,source,created) VALUES(?,?,?,?)",
                      (uid, c["pending_rule"], f"your edit on chat {cid}", self.today().isoformat()))
            self.log(uid, "you", "kept a rule", c["pending_rule"])
        else:
            self.log(uid, "you", "declined a rule", c["pending_rule"])
        self.db.x("UPDATE chats SET pending_rule=NULL WHERE id=? AND user_id=?", (cid, uid))

    # ---------- udhaar
    def _customer(self, uid, name):
        name = clean_text(name, 40)
        if not name:
            raise AppError("Customer name needed")
        c = self.db.one("SELECT id FROM customers WHERE user_id=? AND lower(name)=lower(?)", (uid, name))
        return c["id"] if c else self.db.x("INSERT INTO customers(user_id,name) VALUES(?,?)", (uid, name))

    def ledger_add(self, uid, name, amount, kind, note="", day=None):
        if kind not in ("credit", "payment"):
            raise AppError("kind must be credit or payment")
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise AppError("Amount must be a whole number")
        if not (0 < amount <= 1_000_000):
            raise AppError("Amount out of range")
        cid = self._customer(uid, name)
        self.db.x("INSERT INTO ledger(user_id,customer_id,amount,kind,note,day) VALUES(?,?,?,?,?,?)",
                  (uid, cid, amount, kind, clean_text(note, 100), day or self.today().isoformat()))
        self.log(uid, "you", "udhaar " + kind, f"{clean_text(name, 40)} Rs {amount}")
        return cid

    def balances(self, uid):
        rows = self.db.q("""SELECT c.id,c.name,
            COALESCE(SUM(CASE WHEN l.kind='credit' THEN l.amount ELSE -l.amount END),0) AS owed,
            MAX(l.day) AS last_day FROM customers c LEFT JOIN ledger l ON l.customer_id=c.id AND l.user_id=c.user_id
            WHERE c.user_id=? GROUP BY c.id ORDER BY owed DESC""", (uid,))
        return rows

    def nudge(self, uid, customer_id):
        b = next((x for x in self.balances(uid) if x["id"] == customer_id), None)
        if not b or b["owed"] <= 0:
            raise AppError("Nothing pending for this customer")
        return {"customer": b["name"], "owed": b["owed"], "draft": self._ai(uid, agents.nudge, b["name"], b["owed"])}

    # ---------- nightly check-in
    def parse_checkin(self, uid, text):
        text = clean_text(text, MAX_CHAT)
        if not text:
            raise AppError("Type tonight's note first")
        return self._ai(uid, agents.parse_checkin, text)

    def save_checkin(self, uid, data, raw="", day=None):
        day = day or self.today().isoformat()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise AppError("Bad date")
        vals = {}
        for k in ("cash", "sales", "expenses"):
            try:
                v = int(data.get(k))
            except (TypeError, ValueError):
                raise AppError(f"{k} must be a whole number (use 0 if none)")
            if not (0 <= v <= 10_000_000):
                raise AppError(f"{k} out of range")
            vals[k] = v
        low = [clean_text(x, 40) for x in (data.get("low_stock") or [])][:30]
        self.db.x("""INSERT INTO daily(user_id,day,cash,sales,expenses,low_stock,notes,raw) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id,day) DO UPDATE SET cash=excluded.cash,sales=excluded.sales,expenses=excluded.expenses,
            low_stock=excluded.low_stock,notes=excluded.notes,raw=excluded.raw""",
                  (uid, day, vals["cash"], vals["sales"], vals["expenses"], jdump(low), clean_text(data.get("notes", ""), 300), clean_text(raw, 2000)))
        # udhaar lines are applied only on the same confirm, replacing none (idempotency: caller sends once)
        for e in data.get("udhaar_given") or []:
            self.ledger_add(uid, e["name"], e["amount"], "credit", "night check-in", day)
        for e in data.get("udhaar_received") or []:
            self.ledger_add(uid, e["name"], e["amount"], "payment", "night check-in", day)
        self.log(uid, "you", "saved night check-in", day)

    def checkins(self, uid, month=None):
        rows = self.db.q("SELECT * FROM daily WHERE user_id=? ORDER BY day DESC LIMIT 62", (uid,))
        for r in rows:
            r["low_stock"] = jload(r["low_stock"], [])
        return rows

    def checkin_status(self, uid):
        d = self.today().isoformat()
        r = self.db.one("SELECT id FROM daily WHERE user_id=? AND day=?", (uid, d))
        return {"day": d, "done": bool(r)}

    # ---------- bills inbox
    def add_bill(self, uid, filename="", data=None, text=""):
        text = clean_text(text, 3000)
        path, image = None, None
        if data:
            if len(data) > 2_000_000:
                raise AppError("File too large (max 2 MB)", 413)
            mime, ext = sniff_image(data)
            if not mime:
                raise AppError("Only JPG, PNG or WEBP photos for now")
            d = os.path.join(self.upload_dir, str(uid))
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, new_token()[:24] + ext)
            with open(path, "wb") as f:
                f.write(data)
            image = f"data:{mime};base64," + base64.b64encode(data).decode()
        elif not text:
            raise AppError("Send a photo or paste the bill text")
        ex = self._ai(uid, agents.extract_bill, text, image)
        ok = ex["readable"] and ex["amount"] is not None and ex["date"]
        dup = None
        if ex["amount"] is not None and ex["date"]:
            dup = self.db.one("SELECT id FROM bills WHERE user_id=? AND amount=? AND bill_date=? AND COALESCE(vendor,'')=COALESCE(?,'')",
                              (uid, ex["amount"], ex["date"], ex["vendor"]))
        status = "duplicate" if dup else ("sorted" if ok else "needs_review")
        bid = self.db.x("INSERT INTO bills(user_id,filename,path,vendor,bill_date,amount,category,status,raw,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (uid, clean_text(os.path.basename(filename or ""), 80), path, ex["vendor"], ex["date"], ex["amount"], ex["category"],
                         status, text, self.today().isoformat()))
        self.log(uid, "agents", "sorted a bill", f"bill {bid} {status}")
        return self.bill(uid, bid)

    def bill(self, uid, bid):
        b = self.db.one("SELECT id,filename,vendor,bill_date,amount,category,status,created FROM bills WHERE id=? AND user_id=?", (bid, uid))
        if not b:
            raise AppError("Not found", 404)
        return b

    def bills(self, uid):
        return self.db.q("SELECT id,filename,vendor,bill_date,amount,category,status,created FROM bills WHERE user_id=? ORDER BY id DESC LIMIT 300", (uid,))

    def confirm_bill(self, uid, bid, vendor, bill_date, amount, category):
        self.bill(uid, bid)
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise AppError("Amount must be a whole number")
        if not (0 <= amount <= 10_000_000) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", bill_date or ""):
            raise AppError("Check amount and date (YYYY-MM-DD)")
        if category not in agents.BILL_CATS:
            raise AppError("Unknown category")
        self.db.x("UPDATE bills SET vendor=?,bill_date=?,amount=?,category=?,status='confirmed' WHERE id=? AND user_id=?",
                  (clean_text(vendor, 60), bill_date, amount, category, bid, uid))
        self.log(uid, "you", "confirmed a bill", str(bid))

    def bill_file(self, uid, bid):
        r = self.db.one("SELECT path FROM bills WHERE id=? AND user_id=?", (bid, uid))
        if not r or not r["path"] or not os.path.exists(r["path"]):
            raise AppError("Not found", 404)
        with open(r["path"], "rb") as f:
            data = f.read()
        return data, sniff_image(data)[0]

    # ---------- month-end close (numbers by code, words by model)
    def month_close(self, uid, month):
        if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
            raise AppError("Month like 2026-11")
        y, m = int(month[:4]), int(month[5:])
        if not 1 <= m <= 12:
            raise AppError("Bad month")
        dim = calendar.monthrange(y, m)[1]
        lo, hi = f"{month}-01", f"{month}-{dim:02d}"
        d = self.db.q("SELECT day,sales,expenses,low_stock FROM daily WHERE user_id=? AND day BETWEEN ? AND ?", (uid, lo, hi))
        sales, exp = sum(r["sales"] for r in d), sum(r["expenses"] for r in d)
        have = {r["day"] for r in d}
        last = min(self.today(), dt.date(y, m, dim))
        missing = [f"{month}-{i:02d}" for i in range(1, dim + 1) if dt.date(y, m, i) <= last and f"{month}-{i:02d}" not in have]
        bl = self.db.q("SELECT id,vendor,bill_date,amount,category,status FROM bills WHERE user_id=? AND COALESCE(bill_date,created) BETWEEN ? AND ?", (uid, lo, hi))
        conf = [b for b in bl if b["status"] in ("confirmed", "sorted") and b["amount"] is not None]
        by_cat = {}
        for b in conf:
            by_cat[b["category"]] = by_cat.get(b["category"], 0) + b["amount"]
        review = [b for b in bl if b["status"] in ("needs_review", "duplicate")]
        led = self.db.q("SELECT kind,SUM(amount) a FROM ledger WHERE user_id=? AND day BETWEEN ? AND ? GROUP BY kind", (uid, lo, hi))
        given = next((r["a"] for r in led if r["kind"] == "credit"), 0) or 0
        recd = next((r["a"] for r in led if r["kind"] == "payment"), 0) or 0
        bal = [b for b in self.balances(uid) if b["owed"] > 0]
        stock = sorted({s for r in d for s in jload(r["low_stock"], [])})
        totals = {"sales": sales, "expenses": exp, "bills_total": sum(by_cat.values()), "udhaar_given": given,
                  "udhaar_received": recd, "udhaar_outstanding": sum(b["owed"] for b in bal),
                  "checkin_days": len(have), "days_in_month": dim}
        checklist = []
        if missing:
            checklist.append(f"{len(missing)} day(s) have no night check-in: {', '.join(x[-2:] for x in missing[:10])}{'...' if len(missing) > 10 else ''}. Add them or confirm those days were closed.")
        if review:
            checklist.append(f"{len(review)} bill(s) need your review (unreadable or possible duplicate).")
        for b in bal[:5]:
            checklist.append(f"Collect Rs {b['owed']} from {b['name']} (last entry {b['last_day']}).")
        if stock:
            checklist.append("Reorder or check stock: " + ", ".join(stock[:10]) + ".")
        if totals["bills_total"] and exp and totals["bills_total"] > exp:
            checklist.append("Bills total is more than the expenses you typed at night. Check if some bills were paid later or expenses were missed.")
        summary = self._ai(uid, agents.month_summary, totals) or (
            f"Sales Rs {sales}, expenses Rs {exp}, bills Rs {totals['bills_total']}. Customers owe you Rs {totals['udhaar_outstanding']}. "
            f"Check-ins on {len(have)} of {dim} days.")
        self.log(uid, "agents", "prepared month-end", month)
        return {"month": month, "totals": totals, "bills_by_category": by_cat, "checklist": checklist,
                "missing_days": missing, "summary": summary, "bills_to_review": len(review)}

    # ---------- stock, quick sale, nightly digest
    def _match(self, uid, name):
        n = name.lower().strip()
        items = self.catalog(uid)
        for it in items:
            if it["name"].lower() == n:
                return it
        hits = [it for it in items if n in it["name"].lower() or it["name"].lower() in n]
        return hits[0] if len(hits) == 1 else None

    def stock(self, uid):
        rows = self.db.q("""SELECT c.id,c.name,c.price,COALESCE((SELECT SUM(qty) FROM stock_moves m WHERE m.item_id=c.id AND m.user_id=c.user_id),0) AS expected
            FROM catalog c WHERE c.user_id=? ORDER BY c.name""", (uid,))
        return rows

    def stock_move(self, uid, item_id, qty, kind, note=""):
        if kind not in ("opening", "purchase", "adjust"):
            raise AppError("kind must be opening, purchase or adjust")
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            raise AppError("Quantity must be a whole number")
        if qty == 0 or abs(qty) > 1_000_000 or (kind != "adjust" and qty < 0):
            raise AppError("Quantity out of range")
        if not self.db.one("SELECT id FROM catalog WHERE id=? AND user_id=?", (item_id, uid)):
            raise AppError("Item not found", 404)
        self.db.x("INSERT INTO stock_moves(user_id,item_id,qty,kind,note,day) VALUES(?,?,?,?,?,?)",
                  (uid, item_id, qty, kind, clean_text(note, 100), self.today().isoformat()))
        self.log(uid, "you", "stock " + kind, f"item {item_id} {qty:+d}")

    def stock_count(self, uid, data=None, text=""):
        """Read a photo/note, compare with the ledger. Nothing is saved: the owner reviews first."""
        text = clean_text(text, 1500)
        image = None
        if data:
            if len(data) > 2_000_000:
                raise AppError("File too large (max 2 MB)", 413)
            mime, _ = sniff_image(data)
            if not mime:
                raise AppError("Only JPG, PNG or WEBP photos")
            image = f"data:{mime};base64," + base64.b64encode(data).decode()
        elif not text:
            raise AppError("Send a photo or type the counts")
        ex = self._ai(uid, agents.count_photo, text, image)
        seen, unknown = {}, []
        for l in ex["items"]:
            it = self._match(uid, l["name"])
            if it:
                seen[it["id"]] = seen.get(it["id"], 0) + l["qty"]
            else:
                unknown.append(l)
        rows = []
        for it in self.stock(uid):
            if it["id"] in seen:
                d = seen[it["id"]] - it["expected"]
                rows.append({"item_id": it["id"], "name": it["name"], "expected": it["expected"], "counted": seen[it["id"]],
                             "diff": d, "status": "match" if d == 0 else ("short" if d < 0 else "extra")})
            else:
                rows.append({"item_id": it["id"], "name": it["name"], "expected": it["expected"], "counted": None,
                             "diff": None, "status": "not_seen"})
        return {"readable": ex["readable"], "rows": rows, "unknown": unknown, "ai_count": True}

    def stock_count_confirm(self, uid, fixes):
        """Owner accepts counts for chosen items: records a stock adjust so ledger matches the shelf."""
        n = 0
        for f in fixes or []:
            try:
                iid, counted = int(f["item_id"]), int(f["counted"])
            except (KeyError, TypeError, ValueError):
                continue
            if counted < 0:
                continue
            cur = next((r for r in self.stock(uid) if r["id"] == iid), None)
            if cur and counted != cur["expected"]:
                self.stock_move(uid, iid, counted - cur["expected"], "adjust", "physical count")
                n += 1
        return n

    def purchase_parse(self, uid, data=None, text=""):
        """Read a supplier bill (photo or text) into stock-in lines. Nothing is saved until confirmed."""
        text = clean_text(text, 3000)
        image = None
        if data:
            if len(data) > 2_000_000:
                raise AppError("File too large (max 2 MB)", 413)
            mime, _ = sniff_image(data)
            if not mime:
                raise AppError("Only JPG, PNG or WEBP photos")
            image = f"data:{mime};base64," + base64.b64encode(data).decode()
        elif not text:
            raise AppError("Send the supplier bill photo or paste its text")
        ex = self._ai(uid, agents.read_purchase, text, image)
        lines, unknown = {}, []
        for l in ex["items"]:
            it = self._match(uid, l["name"])
            if it:
                cur = lines.setdefault(it["id"], {"item_id": it["id"], "name": it["name"], "qty": 0})
                cur["qty"] += l["qty"]
            else:
                unknown.append(l)
        return {"readable": ex["readable"], "lines": list(lines.values()), "unknown": unknown}

    def purchase_confirm(self, uid, lines):
        n = 0
        for l in lines or []:
            try:
                iid, q = int(l["item_id"]), int(l["qty"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 < q <= 1_000_000:
                self.stock_move(uid, iid, q, "purchase", "supplier bill")
                n += 1
        if not n:
            raise AppError("Nothing to add")
        return n

    def sale_parse(self, uid, text):
        text = clean_text(text, 500)
        if not text:
            raise AppError("Say or type the sale first")
        ex = self._ai(uid, agents.parse_sale, text)
        lines, unknown, total = [], [], 0
        for l in ex["items"]:
            it = self._match(uid, l["name"])
            if not it:
                unknown.append(l["name"]); continue
            amt = it["price"] * l["qty"]
            total += amt
            lines.append({"item_id": it["id"], "name": it["name"], "qty": l["qty"], "price": it["price"], "amount": amt})
        return {"customer": ex["customer"], "lines": lines, "unknown": unknown, "total": total, "paid": ex["paid"]}

    def sale_confirm(self, uid, customer, lines, paid):
        cat = {c["id"]: c for c in self.catalog(uid)}
        clean, total = [], 0
        for l in lines or []:
            try:
                it, q = cat[int(l["item_id"])], int(l["qty"])
            except (KeyError, TypeError, ValueError):
                raise AppError("Bad bill line")
            if not (0 < q <= 100000):
                raise AppError("Quantity out of range")
            clean.append({"item_id": it["id"], "name": it["name"], "qty": q, "price": it["price"]})
            total += it["price"] * q
        if not clean:
            raise AppError("Nothing to bill")
        try:
            paid = total if paid in (None, "") else int(paid)
        except (TypeError, ValueError):
            raise AppError("Paid must be a whole number")
        paid = max(0, min(paid, total))
        customer = clean_text(customer or "", 40)
        if total - paid > 0 and not customer:
            raise AppError("Add the customer name for the unpaid part")
        day = self.today().isoformat()
        sid = self.db.x("INSERT INTO sales(user_id,customer,lines,total,paid,day) VALUES(?,?,?,?,?,?)",
                        (uid, customer, json.dumps(clean), total, paid, day))
        for l in clean:
            self.db.x("INSERT INTO stock_moves(user_id,item_id,qty,kind,note,day) VALUES(?,?,?,?,?,?)",
                      (uid, l["item_id"], -l["qty"], "sale", f"sale {sid}", day))
        if total - paid > 0:
            self.ledger_add(uid, customer, total - paid, "credit", f"sale {sid}")
        self.log(uid, "you", "confirmed a sale", f"sale {sid} Rs {total}")
        return {"id": sid, "total": total, "paid": paid, "due": total - paid}

    def digest(self, uid, low_at=5):
        """Sleeping mode: only exceptions, all computed by code."""
        todo = []
        if not self.checkin_status(uid)["done"]:
            todo.append("Tonight's check-in is not saved yet.")
        tracked = {r["item_id"] for r in self.db.q("SELECT DISTINCT item_id FROM stock_moves WHERE user_id=?", (uid,))}
        stock = [r for r in self.stock(uid) if r["id"] in tracked]
        neg = [r["name"] for r in stock if r["expected"] < 0]
        low = [r["name"] for r in stock if 0 <= r["expected"] <= low_at]
        if neg:
            todo.append("Ledger shows negative stock (a purchase is missing?): " + ", ".join(neg))
        if low:
            todo.append("Running low in the ledger: " + ", ".join(low))
        owed = [b for b in self.balances(uid) if b["owed"] > 0]
        if owed:
            todo.append(f"{len(owed)} customers owe money, Rs {sum(b['owed'] for b in owed)} in total.")
        nb = self.db.one("SELECT COUNT(*) n FROM bills WHERE user_id=? AND status IN ('needs_review','duplicate')", (uid,))["n"]
        if nb:
            todo.append(f"{nb} bills need a look.")
        last = self.db.one("SELECT MAX(day) d FROM stock_moves WHERE user_id=? AND note='physical count'", (uid,))["d"]
        if stock and (not last or (self.today() - dt.date.fromisoformat(last)).days > 7):
            todo.append("No physical stock check in the last 7 days. Send a shelf photo.")
        return {"all_clear": not todo, "needs_you": todo}

    def activity(self, uid):
        return self.db.q("SELECT ts,actor,action,detail FROM activity WHERE user_id=? ORDER BY id DESC LIMIT 80", (uid,))

    # ---------- demo
    def demo_user(self, ip="?"):
        if not self.rl.allow(("demo", ip), 10, 3600):
            raise AppError("Too many demo sessions from here. Try later.", 429)
        name = "demo-" + new_token()[:8].lower().replace("_", "x").replace("-", "y")
        s = self.register(name, new_token()[:16], "Meera's Jewellery (demo)", ip=ip + "-demo")
        uid = s["user_id"]
        for n, p in (("Jhumka set", 450), ("Oxidised necklace", 650), ("Bangles box", 300)):
            self.add_item(uid, n, p)
        t = self.today()
        for i, (sale, exp_, cash) in enumerate([(5200, 800, 6100), (7400, 1200, 6900), (3100, 400, 7400)], start=1):
            day = (t - dt.timedelta(days=4 - i)).isoformat()
            self.save_checkin(uid, {"cash": cash, "sales": sale, "expenses": exp_, "low_stock": ["thread"] if i == 2 else []}, "", day)
        self.ledger_add(uid, "Anjali", 1200, "credit", "demo")
        self.ledger_add(uid, "Pooja", 450, "credit", "demo")
        self.ledger_add(uid, "Anjali", 300, "payment", "demo")
        return s
