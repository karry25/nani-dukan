import base64, json, threading, unittest, urllib.request, urllib.error
from server import serve
from tests.test_core import mk
from nanidukan import scam
from nanidukan.llm import MockClient
from nanidukan.service import AppError

OWN = "ashastore@okhdfcbank"


class QR(unittest.TestCase):
    def test_own_qr_ok(self):
        v = scam.check_qr(f"upi://pay?pa={OWN}&pn=Asha%20Store", OWN, purpose="verify_own")
        self.assertEqual(v["status"], "ok")
        self.assertIn("your own UPI ID", v["reasons"][0])

    def test_swapped_qr_danger(self):
        v = scam.check_qr("upi://pay?pa=scammer99@ybl&pn=Asha", OWN, purpose="verify_own")
        self.assertEqual(v["status"], "danger")
        self.assertIn("QR-SWAP", v["reasons"][0])

    def test_not_a_upi_qr(self):
        self.assertEqual(scam.check_qr("https://evil.example/pay", OWN)["status"], "unknown")
        self.assertEqual(scam.check_qr("", OWN)["status"], "unknown")

    def test_receive_money_qr_always_danger(self):
        v = scam.check_qr(f"upi://pay?pa={OWN}&am=500", OWN, purpose="receive")
        self.assertEqual(v["status"], "danger")
        self.assertIn("never receive", v["reasons"][0])

    def test_amount_mismatch_warns(self):
        v = scam.check_qr("upi://pay?pa=shop@okicici&am=500", "", expected_amount=450, purpose="pay")
        self.assertEqual(v["status"], "warn")
        self.assertIn("Rs 500", v["reasons"][0])

    def test_no_valid_upi_id(self):
        self.assertEqual(scam.check_qr("upi://pay?pa=not-an-id!", "")["status"], "danger")
        self.assertEqual(scam.check_qr("upi://pay?pn=NoID", "")["status"], "danger")

    def test_upi_validation(self):
        self.assertTrue(scam.valid_upi("asha.store-1@okhdfcbank"))
        self.assertFalse(scam.valid_upi("no-at-sign"))
        self.assertFalse(scam.valid_upi(""))


class Claims(unittest.TestCase):
    def setUp(self):
        self.s = mk()
        self.a = self.s.register("asha", "password1", "Asha Store")["user_id"]
        self.b = self.s.register("bina", "password2", "Bina Store")["user_id"]

    def test_payment_short_flag(self):
        self.s.ledger_add(self.a, "Anjali", 900, "credit")
        c = self.s.add_chat(self.a, "Anjali ne 300 diye kal")
        self.assertTrue(any("Short by Rs 600" in f for f in c["flags"]), c["flags"])

    def test_payment_over_owed_flag(self):
        self.s.ledger_add(self.a, "Anjali", 200, "credit")
        c = self.s.add_chat(self.a, "Anjali ne 500 diye")
        self.assertTrue(any("only Rs 200 pending" in f for f in c["flags"]), c["flags"])

    def test_claim_no_record_flag(self):
        c = self.s.add_chat(self.a, "Ramesh ne 800 paid kar diya, parcel de do")
        self.assertTrue(any("not in your udhaar book" in f for f in c["flags"]), c["flags"])

    def test_claim_no_name_flag(self):
        c = self.s.add_chat(self.a, "payment ho gaya, screenshot bhej raha hoon")
        joined = " ".join(c["flags"])
        self.assertIn("Confirm", joined)
        self.assertIn("screenshot is not proof", joined)

    def test_overpayment_trick_flag(self):
        c = self.s.add_chat(self.a, "Maine 5000 transfer kar diya by mistake, 4500 cash wapas de do")
        self.assertTrue(any("OVERPAYMENT TRICK" in f for f in c["flags"]), c["flags"])

    def test_no_claim_no_flags(self):
        self.s.add_item(self.a, "Jhumka", 450)
        c = self.s.add_chat(self.a, "jhumka ka price batao")
        self.assertEqual(c["flags"], [])

    def test_other_users_ledger_not_used(self):
        self.s.ledger_add(self.b, "Anjali", 900, "credit")
        c = self.s.add_chat(self.a, "Anjali ne 300 diye")
        self.assertTrue(any("not in your udhaar book" in f for f in c["flags"]), c["flags"])


class Watch(unittest.TestCase):
    def setUp(self):
        self.s = mk()
        self.a = self.s.register("asha", "password1", "Asha Store")["user_id"]
        self.b = self.s.register("bina", "password2", "Bina Store")["user_id"]

    def test_add_list_del(self):
        wid = self.s.watch_add(self.a, "Fraud Ravi", "fake screenshot 10 Nov")
        self.assertEqual(self.s.watch_list(self.a)[0]["label"], "Fraud Ravi")
        with self.assertRaises(AppError):
            self.s.watch_add(self.a, "Fraud Ravi")
        with self.assertRaises(AppError):
            self.s.watch_add(self.a, "ab")
        self.s.watch_del(self.a, wid)
        self.assertEqual(self.s.watch_list(self.a), [])

    def test_hit_flags_chat_and_raises_urgency(self):
        self.s.watch_add(self.a, "Fraud Ravi")
        c = self.s.add_chat(self.a, "Fraud Ravi here, jhumka chahiye")
        self.assertEqual(c["urgency"], 3)
        self.assertTrue(any("WATCHLIST" in f for f in c["flags"]), c["flags"])

    def test_phone_hit(self):
        self.s.watch_add(self.a, "9876543210")
        c = self.s.add_chat(self.a, "Call me on 98765 43210 for refund")
        self.assertTrue(any("WATCHLIST" in f for f in c["flags"]), c["flags"])

    def test_isolation(self):
        wid = self.s.watch_add(self.a, "Fraud Ravi")
        self.assertEqual(self.s.watch_list(self.b), [])
        c = self.s.add_chat(self.b, "Fraud Ravi here")
        self.assertFalse(any("WATCHLIST" in f for f in c["flags"]))
        self.s.watch_del(self.b, wid)  # must not delete A's entry
        self.assertEqual(len(self.s.watch_list(self.a)), 1)


class QrFlowAndDigest(unittest.TestCase):
    def setUp(self):
        self.s = mk()
        self.a = self.s.register("asha", "password1", "Asha Store")["user_id"]

    def digest_text(self):
        return " ".join(self.s.digest(self.a)["needs_you"])

    def test_upi_setup_and_daily_check_reminder(self):
        self.assertIn("Add your shop's UPI ID", self.digest_text())
        with self.assertRaises(AppError):
            self.s.set_shop(self.a, "Asha Store", "hinglish", "", upi_id="bad-upi")
        self.s.set_shop(self.a, "Asha Store", "hinglish", "", upi_id=OWN)
        self.assertTrue(self.s.qr_status(self.a)["due"])
        self.assertIn("No QR check in 7 days", self.digest_text())
        v = self.s.qr_check(self.a, f"upi://pay?pa={OWN}&pn=Asha", purpose="verify_own")
        self.assertEqual(v["status"], "ok")
        self.assertFalse(self.s.qr_status(self.a)["due"])
        self.assertNotIn("No QR check", self.digest_text())

    def test_qr_check_logs_and_validates(self):
        with self.assertRaises(AppError):
            self.s.qr_check(self.a, "")
        with self.assertRaises(AppError):
            self.s.qr_check(self.a, "upi://pay?pa=x@ok", expected_amount="abc")
        self.s.qr_check(self.a, "upi://pay?pa=x@okaxis", purpose="pay")
        self.assertTrue(any(a["action"] == "QR check" for a in self.s.activity(self.a)))


class Evidence(unittest.TestCase):
    def setUp(self):
        self.s = mk()
        self.a = self.s.register("asha", "password1", "Asha Store")["user_id"]
        self.b = self.s.register("bina", "password2", "Bina Store")["user_id"]
        self.s.ledger_add(self.a, "Anjali", 1200, "credit", "note one")
        self.s.ledger_add(self.a, "Anjali", 300, "payment")
        self.s.watch_add(self.a, "Anjali", "test entry")
        self.s.add_chat(self.a, "Anjali ne 300 diye")
        self.cid = next(x["id"] for x in self.s.balances(self.a) if x["name"] == "Anjali")

    def test_pack_contents(self):
        pdf, name = self.s.evidence_pack(self.a, self.cid)
        self.assertEqual(name, "Anjali")
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        for needle in (b"Anjali", b"Rs 1200", b"gave on udhaar", b"paid back", b"test entry", b"police complaint"):
            self.assertIn(needle, pdf)
        self.assertTrue(any(a["action"] == "made an evidence pack" for a in self.s.activity(self.a)))

    def test_isolation(self):
        with self.assertRaises(AppError) as e:
            self.s.evidence_pack(self.b, self.cid)
        self.assertEqual(e.exception.code, 404)
        with self.assertRaises(AppError):
            self.s.evidence_pack(self.a, 9999)


class C:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"; self.cookie = None; self.csrf = None

    def call(self, method, path, body=None, csrf=True):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if self.cookie:
            r.add_header("Cookie", self.cookie)
        if csrf and self.csrf:
            r.add_header("X-CSRF", self.csrf)
        try:
            resp = urllib.request.urlopen(r)
        except urllib.error.HTTPError as e:
            resp = e
        if resp.headers.get("Set-Cookie"):
            self.cookie = resp.headers["Set-Cookie"].split(";")[0]
        raw = resp.read()
        try:
            j = json.loads(raw)
        except ValueError:
            j = None
        if j and "csrf" in j and path in ("/api/login", "/api/register", "/api/demo"):
            self.csrf = j["csrf"]
        return resp.status, j, resp.headers, raw


class HTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.svc = serve(port=0, db_path=":memory:", llm=MockClient())
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def user(self, name):
        c = C(self.port)
        st, j, h, _ = c.call("POST", "/api/register", {"username": name, "password": "password1", "shop_name": name})
        self.assertEqual(st, 200)
        return c

    def test_scam_endpoints(self):
        a, b = self.user("scama"), self.user("scamb")
        self.assertEqual(C(self.port).call("GET", "/api/scam")[0], 401)
        st, j, *_ = a.call("POST", "/api/scam/watch", {"label": "Fraud Ravi", "note": "n"})
        self.assertEqual(st, 200)
        wid = j["id"]
        self.assertEqual(a.call("GET", "/api/scam")[1]["watch"][0]["label"], "Fraud Ravi")
        self.assertEqual(b.call("GET", "/api/scam")[1]["watch"], [])
        self.assertEqual(b.call("DELETE", f"/api/scam/watch/{wid}")[0], 200)
        self.assertEqual(len(a.call("GET", "/api/scam")[1]["watch"]), 1)  # B cannot delete A's
        self.assertEqual(a.call("DELETE", f"/api/scam/watch/{wid}")[0], 200)
        st, j, *_ = a.call("POST", "/api/scam/qr", {"text": "upi://pay?pa=scammer99@ybl", "purpose": "verify_own"})
        self.assertEqual(st, 200)
        self.assertEqual(j["status"], "unknown")  # no own UPI set: parsed but unverifiable
        c2 = C(self.port)
        c2.cookie = a.cookie
        self.assertEqual(c2.call("POST", "/api/scam/qr", {"text": "x"}, csrf=False)[0], 403)

    def test_evidence_download(self):
        a = self.user("eva")
        a.call("POST", "/api/ledger", {"name": "Anjali", "amount": 500, "kind": "credit"})
        cid = a.call("GET", "/api/udhaar")[1]["customers"][0]["id"]
        st, j, h, raw = a.call("GET", f"/api/scam/evidence/{cid}")
        self.assertEqual(st, 200)
        self.assertEqual(h["Content-Type"], "application/pdf")
        self.assertTrue(raw.startswith(b"%PDF-1.4"))
        b = self.user("evb")
        self.assertEqual(b.call("GET", f"/api/scam/evidence/{cid}")[0], 404)
        self.assertEqual(C(self.port).call("GET", f"/api/scam/evidence/{cid}")[0], 401)


if __name__ == "__main__":
    unittest.main()
