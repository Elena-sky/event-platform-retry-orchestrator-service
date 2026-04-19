"""Centralized backoff policy (milliseconds per attempt, 1-based attempt index)."""

_DELAY_MS_TIERS = (5000, 30000, 120000, 600000)


def calculate_delay_ms(retry_count: int) -> int:
    """Return delay before the next delivery attempt.

    ``retry_count`` is 1-based (first retry uses index 0 → 5s).
    """
    idx = max(0, retry_count - 1)
    last = len(_DELAY_MS_TIERS) - 1
    return _DELAY_MS_TIERS[min(idx, last)]
