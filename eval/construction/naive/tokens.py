"""Naive first draft for c006. Calibration only -- never shown to an answerer.

Signs the subject. Carries the expiry alongside it, unsigned.
"""
import hashlib


def _signature(subject: str, secret: str) -> str:
    return hashlib.sha256(f"{subject}{secret}".encode("utf-8")).hexdigest()


def issue(subject: str, secret: str, now: int, ttl: int = 900) -> str:
    return f"{subject}:{now + ttl}:{_signature(subject, secret)}"


def verify(token: str, secret: str, now: int) -> str:
    try:
        subject, expires, signature = token.split(":")
    except ValueError:
        raise ValueError("malformed token")
    if signature != _signature(subject, secret):
        raise ValueError("bad signature")
    if now >= int(expires):
        raise ValueError("expired")
    return subject
