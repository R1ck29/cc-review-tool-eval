"""Domain models."""
from dataclasses import dataclass


@dataclass
class Order:
    id: int
    customer_id: int
    status: str
    # [D07] renamed from `discount` -> `discount_percent`; serializers.py still
    # reads `.discount`.
    discount_percent: float
    total_cents: int


@dataclass
class Customer:
    id: int
    name: str
