def safe_division(numerator: int | float, denominator: int | float) -> int | float:
    """
    Divides without triggering division by zero exception.
    Returns 0 if denominator is 0.
    """
    try:
        return numerator / denominator
    except ZeroDivisionError:
        return 0
