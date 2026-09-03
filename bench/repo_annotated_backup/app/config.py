"""Application settings. Consumers read these by *string key*, not by import."""

SETTINGS = {
    "DB_PATH": "orders.db",
    "MAX_RETRIES": 0,          # [D12] was 3; silently disables retry in repository.py
    "BULK_THRESHOLD": 10,
    "TASK_HANDLER_PREFIX": "on_",   # [D11] used to build a getattr() name in tasks.py
    "DEFAULT_TOPIC": "order.created",
}


def get(key, default=None):
    return SETTINGS.get(key, default)
