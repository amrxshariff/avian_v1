"""The price table is data, and stale data here costs money quietly."""

from datetime import date

import pytest

from src import config
from src.claude_classifier import Usage


def test_cost_uses_config_rates():
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert u.cost() == pytest.approx(
        config.INPUT_PER_MTOK + config.OUTPUT_PER_MTOK
    )


def test_cost_accepts_explicit_rates():
    u = Usage(input_tokens=2000, output_tokens=1000)
    assert u.cost(2.0, 10.0) == pytest.approx(0.014)


def test_empty_usage_costs_nothing():
    assert Usage().cost() == 0.0


def test_measured_rate_is_below_the_assumption():
    """The limiter must assume more than the measurement, never less."""
    measured = 0.00095  # tools/measure_cost.py, 26 September 2026
    assert config.ASSUMED_COST_PER_TITLE > measured


def test_a_normal_network_fits_inside_the_generation_cap():
    """If 371 titles can hit the runaway guard, the guard is set wrong."""
    cost = 371 * config.ASSUMED_COST_PER_TITLE
    assert cost < config.MAX_SPEND_PER_GENERATION / 5


def test_generation_cap_fits_inside_the_daily_cap():
    assert config.MAX_SPEND_PER_GENERATION < config.MAX_SPEND_PER_DAY


def test_price_checked_date_is_parseable_and_not_absurd():
    checked = date.fromisoformat(config.PRICE_CHECKED)
    assert date(2025, 1, 1) < checked <= date.today()
