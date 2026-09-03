"""String-keyed pub/sub. Topics are never resolved statically."""
from app.config import get

_SUBSCRIBERS = {}


def subscribe(topic, fn):
    _SUBSCRIBERS.setdefault(topic, []).append(fn)


def publish(topic, payload):
    for fn in _SUBSCRIBERS.get(topic, []):
        fn(payload)


def publish_order_created(payload):
    # [D09] publishes "order.created"; handlers.py subscribes to "order_created".
    publish(get("DEFAULT_TOPIC"), payload)
