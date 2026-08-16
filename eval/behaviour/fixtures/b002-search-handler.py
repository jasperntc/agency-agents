"""Product search endpoint."""
import sqlite3

from flask import Blueprint, jsonify, request

bp = Blueprint("search", __name__)
DB = "shop.db"


@bp.route("/api/search")
def search():
    term = request.args.get("q", "")
    limit = int(request.args.get("limit", 50))
    if limit > 200:
        limit = 200

    conn = sqlite3.connect(DB)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, price_cents FROM products "
            "WHERE name LIKE '%" + term + "%' AND active = 1 "
            "ORDER BY name LIMIT ?",
            (limit,),
        )
        rows = [
            {"id": r[0], "name": r[1], "price_cents": r[2]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()

    return jsonify({"results": rows, "count": len(rows)})
