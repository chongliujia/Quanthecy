import math

import pytest
from quanthecy_analytics.volume import cumulative_delta


def test_audited_counter_noise_is_zero_in_both_directions():
    previous, current = 48732713.555604056, 48732713.55560403
    assert cumulative_delta(previous, current) == 0
    assert cumulative_delta(current, previous) == 0


@pytest.mark.parametrize("base", [0.0, 1.0, 48732713.0, 1e12])
def test_tolerance_boundary_does_not_absorb_larger_changes(base):
    tolerance = max(1e-9, 8 * math.ulp(base))
    assert cumulative_delta(base, base + tolerance / 2) == 0
    assert cumulative_delta(base, base + tolerance * 2) > 0
    assert cumulative_delta(base + tolerance * 2, base) < 0
