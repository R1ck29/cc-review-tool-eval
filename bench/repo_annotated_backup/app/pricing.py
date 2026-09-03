"""Price computation."""
from app.config import get


def apply_bulk_discount(quantity, unit_cents):
    """[D01] off-by-one: the documented rule is 'threshold or more', but the
    comparison is strictly greater-than, so an order of exactly BULK_THRESHOLD
    units is charged full price.
    """
    threshold = get("BULK_THRESHOLD")
    if quantity > threshold:
        return int(unit_cents * quantity * 0.9)
    return unit_cents * quantity


def compute_total(quantity, unit_cents, tax_rate):
    """[D05] `tax_rate` is a new *required* parameter; existing callers in
    orders.py still call compute_total(quantity, unit_cents).
    """
    subtotal = apply_bulk_discount(quantity, unit_cents)
    return int(subtotal * (1 + tax_rate))
