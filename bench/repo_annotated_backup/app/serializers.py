"""Wire (de)serialization. Keys here are a contract with api.py."""
from app.models import Order


def order_to_dict(order: Order):
    return {
        "id": order.id,
        # [D10] api.py reads payload["customerId"] (camelCase).
        "customer_id": order.customer_id,
        "status": order.status,
        # [D07] Order.discount was renamed to Order.discount_percent.
        "discount": order.discount,
        "total_cents": order.total_cents,
    }
