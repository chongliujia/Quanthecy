"""Numerical policy for adjacent cumulative-volume observations, in source units."""

import math

# Eight binary64 representable steps cover the observed serialization noise;
# the absolute floor handles counters near zero. This is not an economic reset
# allowance or a percentage of the counter. Raw observations are never changed.
ABSOLUTE_TOLERANCE = 1e-9
ULP_TOLERANCE = 8


def cumulative_delta(previous: float, current: float) -> float:
    """Return a signed delta, treating precision-scale changes in either direction as zero.

    Callers must validate finite, nonnegative counters and matching units/basis.
    Negative results beyond the tolerance remain evidence of a counter reset.
    """
    tolerance = max(
        ABSOLUTE_TOLERANCE,
        ULP_TOLERANCE * max(math.ulp(previous), math.ulp(current)),
    )
    delta = current - previous
    return 0.0 if abs(delta) <= tolerance else delta
