"""
tests/test_keys.py — D-55: one place reads the key.

The test that matters is the last one. Four resolvers agreed for months; what
stops a fifth is not review but a check that fails when one appears.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dashboard.keys import (
    KEY_NONE,
    KEY_PROJECT,
    KEY_REJECTED,
    KEY_SERVICE_BUSY,
    KEY_USER,
    KEY_VALID,
    MissingKeyError,
    check_key,
    forget_key,
    key_source,
    redact,
    remember_key,
    resolve_client,
    resolve_key,
    session_key,
)

SRC = Path("src")


def test_the_environment_key_is_returned(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert resolve_key() == "sk-ant-test"


def test_no_key_raises_with_something_actionable(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="console.anthropic.com"):
        resolve_key()


def test_the_classifier_and_the_assistant_share_the_error():
    """A caller catching one used to miss the other."""
    from src.assistant import MissingKeyError as from_assistant

    assert from_assistant is MissingKeyError


def test_every_key_source_value_is_truthy():
    """The guard for D-57: truthiness carries no information here, so a
    caller relying on it is wrong by construction rather than by accident."""
    assert all(bool(v) for v in (KEY_USER, KEY_PROJECT, KEY_NONE))


def test_only_one_module_reads_the_key_from_the_environment():
    """D-55's guard. A fifth reader is a silent divergence, not a bug report."""
    offenders = [
        path
        for path in SRC.rglob("*.py")
        if path.name != "keys.py"
        and "ANTHROPIC_API_KEY" in path.read_text(encoding="utf-8")
        and "os.environ" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"reads the key directly: {offenders}"


# --- slice 1: the session key store -------------------------------------------


def test_a_session_key_takes_precedence_over_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-project")
    store: dict = {}
    remember_key("sk-ant-user", store)
    assert resolve_key(store) == "sk-ant-user"


def test_key_source_is_user_with_a_session_key_project_without(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-project")
    store: dict = {}
    assert key_source(store) == KEY_PROJECT
    remember_key("sk-ant-user", store)
    assert key_source(store) == KEY_USER


def test_forget_key_restores_the_project_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-project")
    store: dict = {}
    remember_key("sk-ant-user", store)
    forget_key(store)
    assert key_source(store) == KEY_PROJECT
    assert resolve_key(store) == "sk-ant-project"


def test_an_invalid_key_is_never_stored(monkeypatch):
    monkeypatch.setattr(
        "src.dashboard.keys.validate_key", lambda key, client=None: KEY_REJECTED
    )
    store: dict = {}
    outcome = check_key("sk-ant-bad", store)
    assert outcome == KEY_REJECTED
    assert session_key(store) is None


def test_check_key_calls_validate_key_once_for_the_same_key(monkeypatch):
    calls: list[str] = []

    def fake_validate(key, client=None):
        calls.append(key)
        return KEY_VALID

    monkeypatch.setattr("src.dashboard.keys.validate_key", fake_validate)
    store: dict = {}
    check_key("sk-ant-same", store)
    check_key("sk-ant-same", store)
    assert len(calls) == 1


def test_check_key_calls_again_after_forget_key(monkeypatch):
    calls: list[str] = []

    def fake_validate(key, client=None):
        calls.append(key)
        return KEY_VALID

    monkeypatch.setattr("src.dashboard.keys.validate_key", fake_validate)
    store: dict = {}
    check_key("sk-ant-same", store)
    forget_key(store)
    check_key("sk-ant-same", store)
    assert len(calls) == 2


def test_a_busy_service_is_not_memoised(monkeypatch):
    calls: list[str] = []

    def fake_validate(key, client=None):
        calls.append(key)
        return KEY_SERVICE_BUSY

    monkeypatch.setattr("src.dashboard.keys.validate_key", fake_validate)
    store: dict = {}
    check_key("sk-ant-same", store)
    check_key("sk-ant-same", store)
    assert len(calls) == 2


def test_redact_removes_the_key_from_arbitrary_text():
    store: dict = {}
    remember_key("sk-ant-secret123", store)
    text = "request failed, api_key=sk-ant-secret123 in the body"
    scrubbed = redact(text, store)
    assert "sk-ant-secret123" not in scrubbed
    assert "redacted" in scrubbed


def test_redact_is_a_noop_with_no_session_key():
    text = "nothing to see here"
    assert redact(text, {}) == text


def test_resolve_client_threads_the_store():
    store: dict = {}
    remember_key("sk-ant-threaded", store)
    client = resolve_client(store=store)
    assert client.api_key == "sk-ant-threaded"


# --- D-68: the project key on Community Cloud --------------------------------
#
# Community Cloud has no shell; the project key is entered as a secret. No
# code here reads st.secrets, and none needs to: `streamlit run` calls
# secrets.load_if_toml_exists() at server start (web/bootstrap.py), which
# copies every ROOT-LEVEL string secret into os.environ before app.py runs.
# These pin that mechanism, so a Streamlit upgrade that changes it fails
# here rather than on the deploy. They load secrets the way the server does,
# from a file, into a fresh Secrets object rather than the process singleton.


@pytest.fixture
def _env_restored():
    """Streamlit writes os.environ directly. monkeypatch.delenv on an absent
    variable records nothing to restore, so a probe key would leak into every
    later test (D-62). Restore by hand."""
    import os

    before = os.environ.pop("ANTHROPIC_API_KEY", None)
    yield
    os.environ.pop("ANTHROPIC_API_KEY", None)
    if before is not None:
        os.environ["ANTHROPIC_API_KEY"] = before


def _load_secrets_as_the_server_does(monkeypatch, tmp_path, toml: str) -> None:
    import streamlit
    from streamlit.runtime.secrets import Secrets

    path = tmp_path / "secrets.toml"
    path.write_text(toml, encoding="utf-8")

    real = streamlit.config.get_option
    monkeypatch.setattr(
        streamlit.config, "get_option",
        lambda name: [str(path)] if name == "secrets.files" else real(name),
    )
    secrets = Secrets()
    # A polling watcher thread per test is not wanted, and not under test.
    monkeypatch.setattr(secrets, "_maybe_install_file_watchers", lambda: None)
    assert secrets.load_if_toml_exists()


def test_a_root_level_secret_is_the_project_key(monkeypatch, tmp_path, _env_restored):
    _load_secrets_as_the_server_does(
        monkeypatch, tmp_path, 'ANTHROPIC_API_KEY = "sk-ant-secret-probe"\n')
    assert key_source({}) == KEY_PROJECT
    assert resolve_key({}) == "sk-ant-secret-probe"


def test_a_nested_secret_is_not_found(monkeypatch, tmp_path, _env_restored):
    """The deploy constraint: under a [section], Streamlit does not export it,
    and the app reads the environment. Entered this way, every visitor gets
    the keyless build."""
    _load_secrets_as_the_server_does(
        monkeypatch, tmp_path, '[anthropic]\nANTHROPIC_API_KEY = "sk-ant-nested"\n')
    assert key_source({}) == KEY_NONE
