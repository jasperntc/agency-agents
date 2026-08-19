"""Webhook delivery worker. 12 processes, each with its own pool."""
import random
import time

import httpx
import psycopg_pool

MAX_ATTEMPTS = 6
BASE_DELAY = 0.5
REQUEST_TIMEOUT = 10.0

pool = psycopg_pool.ConnectionPool(
    "postgresql://app@db/app", min_size=4, max_size=40
)


def deliver(url: str, payload: dict) -> bool:
    """POST until the endpoint accepts, or attempts run out."""
    started = time.time()

    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = httpx.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            if resp.status_code < 300:
                return True
            if 400 <= resp.status_code < 500:
                return False
        except httpx.RequestError:
            pass

        if time.time() - started > 120:
            return False

        time.sleep(BASE_DELAY * (2 ** attempt))

    return False


def claim_batch(limit: int = 100):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE deliveries SET state = 'sending' "
            "WHERE id IN (SELECT id FROM deliveries WHERE state = 'pending' "
            "             ORDER BY created_at LIMIT %s) "
            "RETURNING id, url, payload",
            (limit,),
        )
        return cur.fetchall()
