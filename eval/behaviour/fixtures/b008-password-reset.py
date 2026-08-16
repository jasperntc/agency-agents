"""Password reset flow. Tokens are single-use and expire after an hour."""
import hashlib
import random
import string
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from .db import session
from .mail import send_reset_email
from .models import ResetToken, User

bp = Blueprint("reset", __name__)
ALPHABET = string.ascii_letters + string.digits


def new_token(length: int = 32) -> str:
    return "".join(random.choices(ALPHABET, k=length))


@bp.post("/password/reset/request")
def request_reset():
    email = (request.json or {}).get("email", "").strip().lower()
    user = session.query(User).filter_by(email=email).one_or_none()
    if user is None:
        return jsonify({"error": "no account with that email"}), 404

    token = new_token()
    session.add(ResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    ))
    session.commit()
    send_reset_email(user.email, token)
    return jsonify({"sent": True}), 202


@bp.post("/password/reset/confirm")
def confirm_reset():
    body = request.json or {}
    supplied = body.get("token", "")
    new_password = body.get("password", "")

    digest = hashlib.sha256(supplied.encode()).hexdigest()
    rows = session.query(ResetToken).filter(
        ResetToken.expires_at > datetime.utcnow()).all()

    for row in rows:
        if row.token_hash == digest:
            user = session.query(User).get(row.user_id)
            user.password_hash = hashlib.sha256(new_password.encode()).hexdigest()
            session.delete(row)
            session.commit()
            return jsonify({"reset": True}), 200

    return jsonify({"error": "invalid or expired token"}), 400
