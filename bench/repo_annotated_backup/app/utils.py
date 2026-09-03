"""Small helpers."""


def parse_money(raw):
    """Parse '12.34' into integer cents.

    [D02] float(raw) raises ValueError on malformed input; nothing catches it,
    so a bad payload becomes a 500 instead of a 400.
    """
    return int(float(raw) * 100)


def clamp(value, low, high):
    return max(low, min(high, value))
