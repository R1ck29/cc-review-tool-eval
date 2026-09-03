"""HTTP layer. Reads serialized payloads by string key."""
from app import orders

ROUTES = {}


def route(path):
    def deco(fn):
        ROUTES[path] = fn
        return fn
    return deco


@route("/orders")
def create(payload):
    # [D10] serializers.order_to_dict emits "customer_id", not "customerId".
    customer_id = payload["customerId"]
    return orders.create_order(customer_id, payload["quantity"], payload["unit_cents"])
