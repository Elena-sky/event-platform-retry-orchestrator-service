from app.services.retry_logic import calculate_delay_ms


def test_calculate_delay_ms_four_tiers() -> None:
    assert calculate_delay_ms(1) == 5000
    assert calculate_delay_ms(2) == 30000
    assert calculate_delay_ms(3) == 120000
    assert calculate_delay_ms(4) == 600000


def test_calculate_delay_ms_caps_at_longest_tier() -> None:
    assert calculate_delay_ms(99) == 600000
