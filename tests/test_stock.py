import unittest
from tests.test_core import mk, PNG
from nanidukan.service import AppError

class T(unittest.TestCase):
    def setUp(self):
        self.s = mk(); self.a = self.s.register("asha", "password1", "A")["user_id"]; self.b = self.s.register("bina", "password2", "B")["user_id"]
        self.sim = self.s.add_item(self.a, "SIM", 50); self.rc = self.s.add_item(self.a, "Recharge card", 100)
        self.s.stock_move(self.a, self.sim, 100, "opening"); self.s.stock_move(self.a, self.rc, 20, "opening")

    def exp(self, uid, iid): return next(r["expected"] for r in self.s.stock(uid) if r["id"] == iid)

    def test_sale_reduces_stock_and_udhaar(self):
        d = self.s.sale_parse(self.a, "Ramesh ko 10 SIM, 5 Recharge card, paid 300")
        self.assertEqual(d["total"], 1000); self.assertEqual(d["customer"], "Ramesh")
        r = self.s.sale_confirm(self.a, d["customer"], d["lines"], d["paid"])
        self.assertEqual(r["due"], 700); self.assertEqual(self.exp(self.a, self.sim), 90); self.assertEqual(self.exp(self.a, self.rc), 15)
        self.assertEqual(self.s.balances(self.a)[0]["owed"], 700)

    def test_unpaid_needs_name_and_price_from_catalog(self):
        with self.assertRaises(AppError): self.s.sale_confirm(self.a, "", [{"item_id": self.sim, "qty": 1, "price": 1}], 0)
        r = self.s.sale_confirm(self.a, "X", [{"item_id": self.sim, "qty": 2, "price": 1}], None)
        self.assertEqual(r["total"], 100)  # client price ignored

    def test_count_compare_and_confirm(self):
        d = self.s.stock_count(self.a, text="SIM 96, Recharge card 20")
        st = {r["name"]: r["status"] for r in d["rows"]}
        self.assertEqual(st, {"SIM": "short", "Recharge card": "match"})
        self.assertEqual(self.exp(self.a, self.sim), 100)  # nothing saved yet
        self.assertEqual(self.s.stock_count_confirm(self.a, [{"item_id": self.sim, "counted": 96}]), 1)
        self.assertEqual(self.exp(self.a, self.sim), 96)

    def test_unreadable_photo_and_unknown_item(self):
        self.assertFalse(self.s.stock_count(self.a, data=PNG)["readable"])
        self.assertEqual(self.s.stock_count(self.a, text="Pen 5")["unknown"][0]["name"], "Pen")

    def test_isolation_and_digest(self):
        self.assertEqual(self.s.stock(self.b), [])
        with self.assertRaises(AppError): self.s.stock_move(self.b, self.sim, 5, "opening")
        with self.assertRaises(AppError): self.s.sale_confirm(self.b, "X", [{"item_id": self.sim, "qty": 1}], 0)
        self.assertFalse(self.s.digest(self.a)["all_clear"])
        self.assertIn("No physical stock check", " ".join(self.s.digest(self.a)["needs_you"]))

    def test_purchase_bill_to_stock(self):
        d = self.s.purchase_parse(self.a, text="SIM 40, Recharge card 10, Pen 3")
        self.assertEqual({l["name"]: l["qty"] for l in d["lines"]}, {"SIM": 40, "Recharge card": 10})
        self.assertEqual(d["unknown"][0]["name"], "Pen")
        self.assertEqual(self.exp(self.a, self.sim), 100)
        self.assertEqual(self.s.purchase_confirm(self.a, d["lines"]), 2)
        self.assertEqual(self.exp(self.a, self.sim), 140)
        with self.assertRaises(AppError): self.s.purchase_confirm(self.b, [{"item_id": self.sim, "qty": 5}])
        self.assertEqual(self.exp(self.a, self.sim), 140)
