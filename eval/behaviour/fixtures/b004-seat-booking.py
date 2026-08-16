"""Seat reservation for an events service. Runs under gunicorn, 8 workers."""
from flask import Flask, jsonify, request

from .db import session
from .models import Event, Reservation

app = Flask(__name__)


@app.post("/events/<int:event_id>/reserve")
def reserve(event_id: int):
    payload = request.get_json(silent=True) or {}
    qty = payload.get("quantity")
    if not isinstance(qty, int) or qty < 1 or qty > 10:
        return jsonify({"error": "quantity must be an integer 1-10"}), 400

    event = session.query(Event).get(event_id)
    if event is None:
        return jsonify({"error": "no such event"}), 404

    taken = session.query(Reservation).filter_by(event_id=event_id).count()
    if taken + qty > event.capacity:
        return jsonify({"error": "sold out"}), 409

    reservation = Reservation(event_id=event_id, quantity=qty)
    session.add(reservation)
    session.commit()

    return jsonify({"reservation_id": reservation.id, "quantity": qty}), 201
