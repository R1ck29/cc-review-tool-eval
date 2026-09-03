"""Event handlers, wired by topic string."""
from app import events


def on_order_created(payload):
    """[D11] tasks.py resolves this by getattr(handlers, prefix + name)."""
    return f"handled {payload.get('id')}"


# [D09] "order_created" never matches the published "order.created".
events.subscribe("order_created", on_order_created)
