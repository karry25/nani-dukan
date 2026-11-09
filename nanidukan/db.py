import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, pw TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS shops(user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'hinglish', policy TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS catalog(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chats(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL, category TEXT, urgency INTEGER, draft TEXT, final TEXT, flags TEXT, pending_rule TEXT, status TEXT NOT NULL DEFAULT 'new', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL, source TEXT, uses INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', UNIQUE(user_id,name));
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, customer_id INTEGER NOT NULL, amount INTEGER NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', day TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, cash INTEGER NOT NULL, sales INTEGER NOT NULL, expenses INTEGER NOT NULL, low_stock TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', raw TEXT NOT NULL DEFAULT '', UNIQUE(user_id,day));
CREATE TABLE IF NOT EXISTS bills(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, filename TEXT, path TEXT, vendor TEXT, bill_date TEXT, amount INTEGER, category TEXT, status TEXT NOT NULL, raw TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stock_moves(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, item_id INTEGER NOT NULL, qty INTEGER NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', day TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, customer TEXT NOT NULL DEFAULT '', lines TEXT NOT NULL, total INTEGER NOT NULL, paid INTEGER NOT NULL, day TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS usage(user_id INTEGER NOT NULL, day TEXT NOT NULL, calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day));
CREATE TABLE IF NOT EXISTS global_usage(day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0);
"""


class DB:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid


def jdump(o):
    return json.dumps(o, ensure_ascii=False)


def jload(s, default=None):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default
