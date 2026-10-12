"""JSON summaries distinguish unestimable statistics from observed zero."""

import math


def finite_stat(value, digits=None):
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return round(result, digits) if digits is not None else result
