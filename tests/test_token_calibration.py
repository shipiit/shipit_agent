"""The token calibrator: it learns the estimate error, safely."""
from shipit_agent.token_calibration import TokenCalibrator


def test_factor_is_one_before_warmup():
    cal = TokenCalibrator(min_samples=3)
    # A single strong signal must not move the trigger yet.
    cal.observe("gemma-4", estimated=1000, actual=3000)
    assert cal.factor("gemma-4") == 1.0


def test_learns_undercount_after_warmup():
    cal = TokenCalibrator(min_samples=3, alpha=0.5)
    for _ in range(4):
        cal.observe("gemma-4", estimated=1000, actual=1500)  # chars/4 too low
    factor = cal.factor("gemma-4")
    assert factor > 1.0
    # A 1.5x real ratio should pull the factor up toward 1.5.
    assert 1.2 <= factor <= 1.5
    assert cal.calibrated("gemma-4", 1000) >= 1200


def test_never_lowers_below_raw_estimate():
    """Over-count is survivable, under-count kills the run — floor at 1.0."""
    cal = TokenCalibrator(min_samples=3)
    for _ in range(5):
        cal.observe("claude-opus-5", estimated=1000, actual=600)  # we over-estimated
    # Even though actual < estimated, the factor is floored at 1.0.
    assert cal.factor("claude-opus-5") == 1.0
    assert cal.calibrated("claude-opus-5", 1000) == 1000


def test_ratio_is_keyed_per_model():
    cal = TokenCalibrator(min_samples=2, alpha=0.5)
    for _ in range(3):
        cal.observe("gemma-4", estimated=1000, actual=2000)  # dense JSON model
    for _ in range(3):
        cal.observe("claude-opus-5", estimated=1000, actual=1000)  # accurate
    assert cal.factor("gemma-4") > 1.3
    assert cal.factor("claude-opus-5") == 1.0  # not polluted by gemma


def test_single_outlier_is_capped_by_max_factor():
    cal = TokenCalibrator(min_samples=1, max_factor=4.0)
    cal.observe("x", estimated=1, actual=1_000_000)  # broken usage report
    assert cal.factor("x") <= 4.0


def test_zero_or_negative_inputs_are_ignored():
    cal = TokenCalibrator(min_samples=1)
    cal.observe("x", estimated=0, actual=100)
    cal.observe("x", estimated=100, actual=0)
    assert cal.factor("x") == 1.0  # nothing recorded


def test_none_model_uses_a_stable_default_key():
    cal = TokenCalibrator(min_samples=2, alpha=0.5)
    for _ in range(3):
        cal.observe(None, estimated=1000, actual=1600)
    assert cal.factor(None) > 1.0
    assert cal.factor("") == cal.factor(None)  # same default bucket
