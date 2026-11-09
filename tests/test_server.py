import base64, json, threading, unittest, urllib.request, urllib.error
from server import serve
from nanidukan.llm import MockClient

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50

class C:
    def __init__(self, port): self.base = f"http://127.0.0.1:{port}"; self.cookie = None; self.csrf = None
    def call(self, method, path, body=None, csrf=True, raw=None, ctype="application/json"):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None: r.add_header("Content-Type", ctype)
        if self.cookie: r.add_header("Cookie", self.cookie)
        if csrf and self.csrf: r.add_header("X-CSRF", self.csrf)
        try: resp = urllib.request.urlopen(r)
        except urllib.error.HTTPError as e: resp = e
        h = resp.headers
        if h.get("Set-Cookie"): self.cookie = h["Set-Cookie"].split(";")[0]
        b = resp.read()
        try: j = json.loads(b)
        except ValueError: j = None
        if j and "csrf" in j and path in ("/api/login", "/api/register", "/api/demo"): self.csrf = j["csrf"]
        return resp.status, j, h, b

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.svc = serve(port=0, db_path=":memory:", llm=MockClient())
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def user(self, name):
        c = C(self.port); st, j, h, _ = c.call("POST", "/api/register", {"username": name, "password": "password1", "shop_name": name}); self.assertEqual(st, 200); return c

    def test_unauth(self):
        c = C(self.port)
        for p in ("/api/me", "/api/chats", "/api/bills", "/api/udhaar", "/api/month/2026-11"):
            self.assertEqual(c.call("GET", p)[0], 401)

    def test_headers_cookie(self):
        c = C(self.port); st, j, h, _ = c.call("POST", "/api/register", {"username": "hdr1", "password": "password1", "shop_name": "x"})
        sc = h["Set-Cookie"]; self.assertIn("HttpOnly", sc); self.assertIn("SameSite=Strict", sc)
        self.assertIn("default-src 'self'", h["Content-Security-Policy"]); self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertNotIn("session", h["Server"].lower())

    def test_csrf(self):
        c = self.user("csrf1"); c.csrf = None
        st, j, *_ = c.call("POST", "/api/chats", {"text": "price?"}); self.assertEqual(st, 403)
        c.csrf = "wrong"; self.assertEqual(c.call("POST", "/api/ledger", {"name": "a", "amount": 5, "kind": "credit"})[0], 403)

    def test_isolation_http(self):
        a, b = self.user("isoa"), self.user("isob")
        a.call("POST", "/api/catalog", {"name": "Jhumka", "price": 450})
        st, j, *_ = a.call("POST", "/api/chats", {"text": "jhumka price?"}); cid = j["id"]
        st, j, *_ = a.call("POST", "/api/bills", {"text": "Sharma 12/11/2026 total Rs 2400 stock"}); bid = j["id"]
        self.assertEqual(b.call("GET", "/api/bills")[1]["bills"], [])
        self.assertEqual(b.call("GET", f"/api/bills/{bid}/file")[0], 404)
        self.assertEqual(b.call("POST", f"/api/chats/{cid}/edit", {"final": "x"})[0], 404)
        self.assertEqual(b.call("GET", "/api/catalog")[1]["items"], [])

    def test_upload_and_file(self):
        a, b = self.user("upa"), self.user("upb")
        st, j, *_ = a.call("POST", "/api/bills", {"filename": "../../etc/x.png", "data": base64.b64encode(PNG).decode()})
        self.assertEqual(st, 200); self.assertNotIn("/", j["filename"])
        st, _, h, body = a.call("GET", f"/api/bills/{j['id']}/file"); self.assertEqual((st, body), (200, PNG)); self.assertEqual(h["Content-Type"], "image/png")
        self.assertEqual(a.call("POST", "/api/bills", {"filename": "a.exe", "data": base64.b64encode(b"MZ" + b"0" * 60).decode()})[0], 400)

    def test_bad_input(self):
        a = self.user("bad1")
        self.assertEqual(a.call("POST", "/api/chats", raw=b"{not json", ctype="application/json")[0], 400)
        self.assertEqual(a.call("POST", "/api/chats", raw=b"text=hi", ctype="text/plain")[0], 415)
        self.assertEqual(a.call("POST", "/api/chats", raw=b"[1]")[0], 400)
        self.assertEqual(a.call("GET", "/api/nope")[0], 404)
        self.assertEqual(a.call("GET", "/../server.py")[0], 404)
        self.assertEqual(a.call("GET", "/%2e%2e/server.py")[0], 404)
        self.assertEqual(a.call("GET", "/month/2026-11")[0], 404)
        self.assertEqual(a.call("GET", "/api/month/2026-13")[0], 400)

    def test_flow_and_logout(self):
        a = self.user("flow1")
        st, j, *_ = a.call("POST", "/api/checkin/parse", {"text": "aaj sale 5200, kharcha 800, cash 6100"}); self.assertEqual(j["sales"], 5200)
        self.assertEqual(a.call("POST", "/api/checkin/save", {"data": j, "raw": "x"})[0], 200)
        self.assertTrue(a.call("GET", "/api/me")[1]["checkin"]["done"])
        a.call("POST", "/api/logout", {}); self.assertEqual(a.call("GET", "/api/me")[0], 401)

    def test_xss_stored_as_text(self):
        a = self.user("xss1")
        a.call("POST", "/api/chats", {"text": "<script>alert(1)</script> price"})
        self.assertIn("<script>", a.call("GET", "/api/chats")[1]["chats"][0]["text"])  # stored raw; UI must render as text

    def test_demo(self):
        c = C(self.port); self.assertEqual(c.call("POST", "/api/demo", {})[0], 200); self.assertTrue(c.call("GET", "/api/udhaar")[1]["customers"])

if __name__ == "__main__": unittest.main()
