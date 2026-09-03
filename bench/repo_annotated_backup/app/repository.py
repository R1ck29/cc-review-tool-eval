"""Repository layer: turns rows into models."""
from app import db
from app.config import get
from app.models import Order


def get_order(order_id):
    """[D06] now returns None on a miss where it previously raised KeyError."""
    attempts = get("MAX_RETRIES") + 1   # [D12] MAX_RETRIES=0 -> a single attempt
    for _ in range(attempts):
        row = db.fetch_order_row(order_id)
        if row:
            return Order(*row)
    return None
