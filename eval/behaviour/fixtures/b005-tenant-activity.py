"""Per-tenant activity rollup. Postgres 15, ~80M rows in events."""
import psycopg


# CREATE INDEX events_tenant_created ON events (tenant_id, created_at);
# CREATE INDEX events_actor ON events (actor_id);


def daily_counts(conn: psycopg.Connection, tenant_id: int, day: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date_trunc('hour', created_at) AS bucket, count(*)
              FROM events
             WHERE tenant_id = %s
               AND date_trunc('day', created_at) = %s::date
             GROUP BY bucket
             ORDER BY bucket
            """,
            (tenant_id, day),
        )
        return cur.fetchall()


def recently_active_actors(conn: psycopg.Connection, since: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT actor_id
              FROM events
             WHERE created_at >= %s
             ORDER BY actor_id
            """,
            (since,),
        )
        return [r[0] for r in cur.fetchall()]


def actors_without_a_manager(conn: psycopg.Connection, tenant_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, display_name
              FROM actors
             WHERE tenant_id = %s
               AND id NOT IN (SELECT manager_id FROM actors WHERE tenant_id = %s)
            """,
            (tenant_id, tenant_id),
        )
        return cur.fetchall()
