"""Nani Dukan HTTP server (stdlib). JSON API under /api, static UI under /."""
import json, os, re, sys
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from nanidukan.db import DB
from nanidukan.llm import client_from_env
from nanidukan.service import Service, AppError

ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_BODY = 3_000_000
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SEC = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
       "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"}


class _Done(Exception):
    pass


def make_handler(svc, demo_enabled=True, secure_cookie=False):
    class H(BaseHTTPRequestHandler):
        server_version = "NaniDukan"
        sys_version = ""

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in {**SEC, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _token(self):
            c = SimpleCookie(self.headers.get("Cookie", ""))
            return c["sid"].value if "sid" in c else None

        def _cookie(self, tok):
            flags = "; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800" + ("; Secure" if secure_cookie else "")
            return {"Set-Cookie": f"sid={tok}{flags}"}

        def _ip(self):
            return self.client_address[0]

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_DELETE(self):
            self._route("DELETE")

        def _route(self, method):
            path = urlparse(self.path).path
            try:
                if not path.startswith("/api/"):
                    return self._static(path) if method == "GET" else self._send(405, {"error": "no"})
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._send(413, {"error": "Too large"})
                raw = self.rfile.read(n) if n else b""
                ctype = self.headers.get("Content-Type", "")
                body = {}
                if raw:
                    if not ctype.startswith("application/json"):
                        return self._send(415, {"error": "JSON only"})
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise AppError("Bad request")
                out, extra = self._api(method, path[5:], body)
                self._send(200, out, extra=extra)
            except _Done:
                pass
            except AppError as e:
                self._send(e.code, {"error": str(e)})
            except (ValueError, KeyError, TypeError):
                self._send(400, {"error": "Bad request"})
            except Exception:
                self._send(500, {"error": "Something went wrong"})

        def _static(self, path):
            if path in ("/", ""):
                path = "/index.html"
            if not re.fullmatch(r"/[A-Za-z0-9_.-]+", path):
                return self._send(404, {"error": "Not found"})
            f = os.path.join(ROOT, "static", path[1:])
            if not os.path.isfile(f):
                return self._send(404, {"error": "Not found"})
            ct = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}.get(path.rsplit(".", 1)[-1], "application/octet-stream")
            with open(f, "rb") as fh:
                self._send(200, fh.read(), ct)

        def _api(self, method, p, b):
            ip = self._ip()
            if method == "POST" and p == "register":
                s = svc.register(b.get("username"), b.get("password"), b.get("shop_name"), ip)
                return {"csrf": s["csrf"]}, self._cookie(s["token"])
            if method == "POST" and p == "login":
                s = svc.login(b.get("username"), b.get("password"), ip)
                return {"csrf": s["csrf"]}, self._cookie(s["token"])
            if method == "POST" and p == "demo":
                if not demo_enabled:
                    raise AppError("Demo is off", 404)
                s = svc.demo_user(ip)
                return {"csrf": s["csrf"]}, self._cookie(s["token"])
            tok = self._token()
            me = svc.auth(tok)
            if not me:
                raise AppError("Please sign in", 401)
            if method != "GET" and self.headers.get("X-CSRF") != me["csrf"]:
                raise AppError("Bad CSRF token", 403)
            u = me["user_id"]
            ok = ({"ok": True}, None)
            if method == "GET":
                if p == "me":
                    return {"username": me["username"], "csrf": me["csrf"], "shop": svc.shop(u), "usage": svc.usage(u),
                            "checkin": svc.checkin_status(u)}, None
                if p == "catalog": return {"items": svc.catalog(u)}, None
                if p == "rules": return {"rules": svc.rules(u)}, None
                if p == "chats": return {"chats": svc.chats(u)}, None
                if p == "udhaar": return {"customers": svc.balances(u)}, None
                if p == "checkins": return {"days": svc.checkins(u)}, None
                if p == "bills": return {"bills": svc.bills(u)}, None
                if p == "stock": return {"items": svc.stock(u)}, None
                if p == "digest": return svc.digest(u), None
                if p == "scam": return {"watch": svc.watch_list(u), "qr": svc.qr_status(u)}, None
                m = re.fullmatch(r"scam/evidence/(\d+)", p)
                if m:
                    pdf, name = svc.evidence_pack(u, int(m.group(1)))
                    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", name)[:40] or "customer"
                    self._send(200, pdf, "application/pdf",
                               {"Content-Disposition": f"attachment; filename=evidence-{safe}.pdf"})
                    raise _Done()
                if p == "activity": return {"activity": svc.activity(u)}, None
                m = re.fullmatch(r"month/(\d{4}-\d{2})", p)
                if m: return svc.month_close(u, m.group(1)), None
                m = re.fullmatch(r"bills/(\d+)/file", p)
                if m:
                    data, mime = svc.bill_file(u, int(m.group(1)))
                    self._send(200, data, mime, {"Content-Disposition": "inline"})
                    raise _Done()
                raise AppError("Not found", 404)
            if method == "DELETE":
                m = re.fullmatch(r"(rules|catalog)/(\d+)", p)
                if m:
                    (svc.del_rule if m.group(1) == "rules" else svc.del_item)(u, int(m.group(2)))
                    return ok
                m = re.fullmatch(r"scam/watch/(\d+)", p)
                if m:
                    svc.watch_del(u, int(m.group(1))); return ok
                if p == "account":
                    svc.delete_account(u); return ok
                raise AppError("Not found", 404)
            # POST
            if p == "logout": svc.logout(tok); return ok
            if p == "shop": svc.set_shop(u, b.get("name"), b.get("language"), b.get("policy"), b.get("upi_id")); return ok
            if p == "catalog": return {"id": svc.add_item(u, b.get("name"), b.get("price"))}, None
            if p == "chats": return svc.add_chat(u, b.get("text")), None
            m = re.fullmatch(r"chats/(\d+)/(edit|rule)", p)
            if m:
                cid = int(m.group(1))
                if m.group(2) == "edit": return svc.submit_edit(u, cid, b.get("final")), None
                svc.decide_rule(u, cid, bool(b.get("keep"))); return ok
            if p == "ledger":
                svc.ledger_add(u, b.get("name"), b.get("amount"), b.get("kind"), b.get("note", "")); return ok
            m = re.fullmatch(r"udhaar/(\d+)/nudge", p)
            if m: return svc.nudge(u, int(m.group(1))), None
            if p == "scam/watch": return {"id": svc.watch_add(u, b.get("label"), b.get("note", ""))}, None
            if p == "scam/qr": return svc.qr_check(u, b.get("text"), b.get("expected_amount"), b.get("purpose") or "verify_own"), None
            if p == "checkin/parse": return svc.parse_checkin(u, b.get("text")), None
            if p == "checkin/save":
                svc.save_checkin(u, b.get("data") or {}, b.get("raw", ""), b.get("day")); return ok
            if p == "bills":
                import base64
                data = base64.b64decode(b["data"], validate=True) if b.get("data") else None
                return svc.add_bill(u, b.get("filename", ""), data, b.get("text", "")), None
            if p == "stock/move": svc.stock_move(u, b.get("item_id"), b.get("qty"), b.get("kind"), b.get("note", "")); return ok
            if p == "stock/count":
                import base64
                data = base64.b64decode(b["data"], validate=True) if b.get("data") else None
                return svc.stock_count(u, data, b.get("text", "")), None
            if p == "stock/count/confirm": return {"adjusted": svc.stock_count_confirm(u, b.get("fixes"))}, None
            if p == "purchase/parse":
                import base64
                data = base64.b64decode(b["data"], validate=True) if b.get("data") else None
                return svc.purchase_parse(u, data, b.get("text", "")), None
            if p == "purchase/confirm": return {"added": svc.purchase_confirm(u, b.get("lines"))}, None
            if p == "sale/parse": return svc.sale_parse(u, b.get("text")), None
            if p == "sale/confirm": return svc.sale_confirm(u, b.get("customer"), b.get("lines"), b.get("paid")), None
            m = re.fullmatch(r"bills/(\d+)/confirm", p)
            if m:
                svc.confirm_bill(u, int(m.group(1)), b.get("vendor"), b.get("bill_date"), b.get("amount"), b.get("category")); return ok
            raise AppError("Not found", 404)
    return H


def serve(host="127.0.0.1", port=8080, db_path=None, llm=None, demo=True):
    db = DB(db_path or os.path.join(ROOT, "data", "app.db"))
    svc = Service(db, llm or client_from_env(), upload_dir=os.path.join(ROOT, "data", "uploads"))
    H = make_handler(svc, demo)
    srv = ThreadingHTTPServer((host, port), H)
    return srv, svc


if __name__ == "__main__":
    srv, _ = serve(port=int(os.environ.get("PORT", 8080)), demo=os.environ.get("DEMO", "1") == "1")
    print("Nani Dukan on http://127.0.0.1:%s" % srv.server_address[1])
    srv.serve_forever()
