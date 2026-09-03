"""Raw SQL access layer."""
import sqlite3

from app.config import get


def connect():
    return sqlite3.connect(get("DB_PATH"))


def fetch_order_row(order_id):
    """[D04] the connection leaks whenever the query raises: no try/finally and
    no context manager, and the close() below is unreachable on the error path.
    """
    conn = connect()
    cur = conn.cursor()
    # [D08] column is `discount_percent` in schema.sql, not `discount_pct`.
    cur.execute(
        "SELECT id, customer_id, status, discount_pct, total_cents "
        "FROM orders WHERE id = ?",
        (order_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row
