"""Billing boundaries and CLI response handling; no network, credentials, or database needed."""

import json
from types import SimpleNamespace

import pytest

from app.llm import client as llm


@pytest.fixture
def subscription(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_backend", "claude_code")
    monkeypatch.setattr(llm.settings, "claude_code_oauth_token", "test-subscription-token")
    monkeypatch.setattr(llm.settings, "anthropic_api_key", "test-api-key")
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/test/claude")

    def unexpected_api(**kwargs):
        pytest.fail("Subscription mode must never construct an API-key client")

    monkeypatch.setattr(llm.anthropic, "Anthropic", unexpected_api)


def test_subscription_completion_isolates_credentials_and_settings(subscription, monkeypatch, caplog):
    excluded = (
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_HOST_CREDS_FILE",
        "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", "CCR_OAUTH_TOKEN_FILE", "CLAUDE_CODE_SIMPLE",
    )
    for key in excluded:
        monkeypatch.setenv(key, "must-not-be-used")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "wrong-inherited-token")
    monkeypatch.setenv("PATH", "/test/bin")

    def run(cmd, **kwargs):
        env = kwargs["env"]
        assert all(key not in env for key in excluded)
        assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "test-subscription-token"
        assert env["PATH"] == "/test/bin"
        assert cmd[cmd.index("--setting-sources") + 1] == ""
        assert cmd[cmd.index("--tools") + 1] == ""
        assert json.loads(cmd[cmd.index("--mcp-config") + 1]) == {"mcpServers": {}}
        assert "--strict-mcp-config" in cmd
        assert "--bare" not in cmd
        assert kwargs["input"] == "hello"
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "subtype": "success", "result": "ok",
            "modelUsage": {"claude-sonnet-5": {}}, "total_cost_usd": 0.01,
        }), stderr="")

    monkeypatch.setattr(llm.subprocess, "run", run)
    with caplog.at_level("INFO"):
        response = llm.make_llm_client().messages.create(
            model="claude-sonnet-5", system="Return text", messages=[{"role": "user", "content": "hello"}],
        )
    assert response.content[0].text == "ok"
    assert "actual_models=['claude-sonnet-5']" in caplog.text
    assert "test-subscription-token" not in caplog.text


@pytest.mark.parametrize("missing", ["cli", "token"])
def test_missing_subscription_setup_never_falls_back_to_paid_api(subscription, monkeypatch, missing):
    if missing == "cli":
        monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    else:
        monkeypatch.setattr(llm.settings, "claude_code_oauth_token", "")
    with pytest.raises(RuntimeError, match="Refusing to fall back"):
        llm.make_llm_client()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_subscription_exhaustion_stops_without_api_fallback(subscription, monkeypatch, exit_code):
    monkeypatch.setattr(llm.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=exit_code,
        stdout=json.dumps({"subtype": "error", "is_error": True, "result": "Usage limit reached"}),
        stderr="Usage limit reached" if exit_code else "",
    ))
    with pytest.raises(llm.LLMUsageLimitError):
        llm.make_llm_client().messages.create(
            model="claude-opus-5", messages=[{"role": "user", "content": "hello"}],
        )
