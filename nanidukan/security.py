"""Security helpers: password hashing, tokens, text cleaning, rate limits, upload checks."""
import hashlib
import hmac
import os
import re
import secrets
import threading
import time

MAX_CHAT = 2000
MAX_NOTE = 600


def hash_password(password: str, salt: bytes = None):
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return salt.hex(), h.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, h = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(h, hash_hex)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(s, limit=MAX_CHAT) -> str:
    """Untrusted text: drop control chars, trim, cap length."""
    s = _CTRL.sub("", str(s or "")).strip()
    return s[:limit]


def fence(s: str) -> str:
    """Make untrusted text safe to put inside <tag>...</tag> in a prompt:
    it cannot close or open our tags."""
    return s.replace("<", "(").replace(">", ")")


def valid_username(u: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", u or ""))


def valid_password(p: str) -> bool:
    return isinstance(p, str) and 8 <= len(p) <= 128


class RateLimiter:
    """In-memory sliding window. Fine for one server process."""

    def __init__(self):
        self.hits = {}
        self.lock = threading.Lock()

    def allow(self, key, limit, window):
        now = time.time()
        with self.lock:
            q = [t for t in self.hits.get(key, []) if now - t < window]
            if len(q) >= limit:
                self.hits[key] = q
                return False
            q.append(now)
            self.hits[key] = q
            return True

    def clear(self, key):
        with self.lock:
            self.hits.pop(key, None)


def sniff_image(b: bytes):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None, None
