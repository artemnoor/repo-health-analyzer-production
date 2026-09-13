from src.app import calculate_total


def test_calculate_total() -> None:
    assert calculate_total([1, 2, 3]) == 6
