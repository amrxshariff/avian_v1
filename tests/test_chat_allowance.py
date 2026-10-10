import pytest

from src import config
from src.dashboard.chat_allowance import (
    Allowance,
    current,
    record_question,
)
from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER


def test_own_key_is_never_metered():
    a = current({}, KEY_USER)
    assert not a.metered
    assert not a.spent
    assert a.caption() == ""


def test_fresh_session_has_the_full_allowance():
    assert current({}, KEY_PROJECT).remaining == config.FREE_CHAT_QUESTIONS


def test_counting_decrements():
    s = {}
    record_question(s, KEY_PROJECT)
    assert current(s, KEY_PROJECT).remaining == config.FREE_CHAT_QUESTIONS - 1


def test_allowance_is_spent_at_the_cap():
    s = {}
    for _ in range(config.FREE_CHAT_QUESTIONS):
        record_question(s, KEY_PROJECT)
    a = current(s, KEY_PROJECT)
    assert a.spent and a.remaining == 0


def test_counting_past_the_cap_does_not_go_negative():
    a = Allowance(metered=True, asked=config.FREE_CHAT_QUESTIONS + 5)
    assert a.remaining == 0


def test_own_key_does_not_consume_the_count():
    s = {}
    record_question(s, KEY_USER)
    assert current(s, KEY_PROJECT).remaining == config.FREE_CHAT_QUESTIONS


def test_no_key_is_not_metered():
    """Nothing to meter — there is no chat without a key at all."""
    assert not current({}, KEY_NONE).metered


def test_singular_wording_at_one():
    a = Allowance(metered=True, asked=config.FREE_CHAT_QUESTIONS - 1)
    assert "1 free question left" == a.caption()


def test_spent_caption_points_at_the_key():
    a = Allowance(metered=True, asked=config.FREE_CHAT_QUESTIONS)
    assert "key" in a.caption()
