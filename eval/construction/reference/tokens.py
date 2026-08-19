"""Reference implementation for c006. Not shown to any answerer."""
import base64
import hashlib
import hmac
import json


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), payload.encode("ascii"),
                   hashlib.sha256)
    return _b64(mac.digest())


def issue(subject: str, secret: str, now: int, ttl: int = 900) -> str:
    # The expiry is inside the signed payload, not alongside it: a lifetime
    # the holder can edit is not a lifetime.
    claims = json.dumps({"sub": subject, "exp": int(now) + int(ttl)},
                        separators=(",", ":"), sort_keys=True)
    payload = _b64(claims.encode("utf-8"))
    return f"{payload}.{_sign(payload, secret)}"


def verify(token: str, secret: str, now: int) -> str:
    payload, dot, signature = str(token).partition(".")
    if not dot or not payload or not signature:
        raise ValueError("malformed token")

    # compare_digest, not ==: the comparison runs against attacker-supplied
    # input and an early exit leaks the signature a byte at a time.
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        raise ValueError("bad signature")

    try:
        claims = json.loads(_unb64(payload))
        subject, expires = claims["sub"], int(claims["exp"])
    except Exception as exc:
        raise ValueError("malformed payload") from exc

    if int(now) >= expires:
        raise ValueError("expired")
    return subject
