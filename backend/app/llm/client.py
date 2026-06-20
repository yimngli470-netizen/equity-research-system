"""LLM client factory — the single switch between dev (subscription) and prod (API key).

Every place that talks to Claude builds its client through `make_llm_client()` instead of
constructing `anthropic.Anthropic(...)` directly. The factory returns one of two things, chosen by
`settings.llm_backend` (set per-env in config/<app_env>.yaml):

  • "api"          → a real `anthropic.Anthropic` client, billed to ANTHROPIC_API_KEY. PROD path,
                     unchanged behavior. Also what the e2e test exercises (it patches
                     `anthropic.Anthropic`, which this branch still calls by attribute).
  • "claude_code"  → `ClaudeCodeClient`, a drop-in adapter that routes each completion through the
                     `claude` CLI in print mode using CLAUDE_CODE_OAUTH_TOKEN, so calls bill to your
                     Max/Pro SUBSCRIPTION instead of API credits. DEV path (local docker only).

The adapter duck-types only the slice of the Anthropic SDK this codebase uses — all 8 call sites do:

    resp = client.messages.create(model=, max_tokens=, system=, messages=[{"role":"user",...}])
    text = resp.content[0].text

so the adapter exposes exactly that shape and the call sites need no other change.

Safety: the dev backend FAILS LOUDLY if the CLI or token is missing. It never silently falls back to
the API key (that would quietly bill credits — the whole point is to avoid that in dev).
"""

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

# Opus analyst calls can stream large JSON for a while; give the subprocess generous headroom.
_CLI_TIMEOUT_S = 600


class LLMUsageLimitError(RuntimeError):
    """The subscription's usage/rate limit was hit. Distinct so callers (the orchestrator) can stop
    the run cleanly and tell you to re-run later to resume — rather than failing every remaining
    agent one by one."""


# Markers in the CLI's error output that mean "subscription limit", not a generic failure.
_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "limit reached",
    "limit will reset",
    "resets at",
    "too many requests",
    "429",
)


def _is_usage_limit(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _LIMIT_MARKERS)

# Notional API-equivalent price per 1M tokens (input, output) by model family — used only to log a
# rough $ figure so you can see what each call WOULD cost on the API (on the subscription path it's
# what you're saving). Keep roughly in sync with the claude-api skill price table.
_PRICE_PER_MTOK = {
    "opus": (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
    "fable": (10.0, 50.0),
}


def _family(model: str | None) -> str | None:
    m = (model or "").lower()
    for fam in _PRICE_PER_MTOK:
        if fam in m:
            return fam
    return None


def _tier_of(model: str | None) -> str:
    if model == settings.opus_model:
        return "opus"
    if model == settings.sonnet_model:
        return "sonnet"
    return _family(model) or "?"


def _notional_cost(model: str | None, in_tok: int, out_tok: int) -> float | None:
    fam = _family(model)
    if fam is None:
        return None
    p_in, p_out = _PRICE_PER_MTOK[fam]
    return round(in_tok / 1e6 * p_in + out_tok / 1e6 * p_out, 4)


def make_llm_client():
    """Return an LLM client for the active backend. See module docstring."""
    if settings.llm_backend == "claude_code":
        return ClaudeCodeClient()
    if settings.llm_backend == "api":
        # Attribute access (not a stored import) so the e2e test's monkeypatch of
        # anthropic.Anthropic still takes effect here. Wrapped so each call logs the backend + cost.
        return _ApiLoggingClient(anthropic.Anthropic(api_key=settings.anthropic_api_key))
    raise ValueError(
        f"Unknown llm_backend {settings.llm_backend!r} — expected 'api' or 'claude_code'. "
        "Check config/<app_env>.yaml or the LLM_BACKEND env var."
    )


# ── Prod (API key) path: transparent wrapper that logs backend + notional cost per call ───────────
class _ApiLoggingMessages:
    def __init__(self, inner):
        self._inner = inner

    def create(self, **kw):
        resp = self._inner.create(**kw)
        model = kw.get("model")
        try:
            u = resp.usage
            cost = _notional_cost(model, u.input_tokens, u.output_tokens)
            logger.info(
                "LLM via Anthropic API key: model=%s notional_cost_usd=%s tier=%s",
                model, cost, _tier_of(model),
            )
        except Exception:
            pass  # never let logging break a real call (e.g. a fake response without .usage in tests)
        return resp


class _ApiLoggingClient:
    """Wraps anthropic.Anthropic so each .messages.create() logs the backend + cost; delegates the
    rest unchanged so it's a transparent stand-in."""

    def __init__(self, inner):
        self._inner = inner
        self.messages = _ApiLoggingMessages(inner.messages)

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ── Response shapes (mirror the Anthropic SDK fields the call sites read) ─────────────────────────
@dataclass
class _TextBlock:
    text: str


@dataclass
class _Response:
    content: list


class _Messages:
    """Mimics `client.messages` — only `.create(...)` is implemented."""

    def __init__(self, parent: "ClaudeCodeClient"):
        self._parent = parent

    def create(self, *, model: str, messages: list, system: str | None = None,
               max_tokens: int | None = None, **_ignored):
        text = self._parent._complete(model=model, system=system, messages=messages)
        return _Response(content=[_TextBlock(text=text)])


class ClaudeCodeClient:
    """Drop-in stand-in for `anthropic.Anthropic` that bills the subscription via the `claude` CLI."""

    def __init__(self):
        self._cli = shutil.which("claude")
        if not self._cli:
            raise RuntimeError(
                "llm_backend='claude_code' but the `claude` CLI is not installed in this container. "
                "This is the DEV (subscription) backend — the CLI is installed via the build arg "
                "INSTALL_CLAUDE_CLI=1 (see backend/Dockerfile / docker-compose.yml). Refusing to fall "
                "back to the API key (that would bill credits)."
            )
        if not settings.claude_code_oauth_token:
            raise RuntimeError(
                "llm_backend='claude_code' but CLAUDE_CODE_OAUTH_TOKEN is unset. Run `claude "
                "setup-token` on the host and put the token in .env. Refusing to fall back to the API "
                "key (that would bill credits)."
            )
        self.messages = _Messages(self)

    def _complete(self, *, model: str, system: str | None, messages: list) -> str:
        # Concatenate the user turns into a single prompt (the call sites only ever send one user
        # message; join defensively in case that changes).
        user_text = "\n\n".join(
            m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            for m in messages
            if m.get("role") == "user"
        )

        cmd = [self._cli, "-p", "--output-format", "json", "--model", model]
        if system:
            # Replace (not append) Claude Code's default coding system prompt, and strip its dynamic
            # context sections, so the model behaves like a plain completion endpoint.
            cmd += ["--system-prompt", system, "--exclude-dynamic-system-prompt-sections"]

        # Use the subscription token; scrub any API key so the CLI can't bill credits instead.
        env = dict(os.environ)
        env["CLAUDE_CODE_OAUTH_TOKEN"] = settings.claude_code_oauth_token
        env.pop("ANTHROPIC_API_KEY", None)

        try:
            proc = subprocess.run(
                cmd, input=user_text, capture_output=True, text=True,
                env=env, cwd="/tmp", timeout=_CLI_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI timed out after {_CLI_TIMEOUT_S}s") from e

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout)[:500]
            if _is_usage_limit(detail):
                raise LLMUsageLimitError(detail)
            raise RuntimeError(f"claude CLI exited {proc.returncode}: {detail}")

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"claude CLI returned non-JSON: {proc.stdout[:500]}") from e

        if envelope.get("is_error") or envelope.get("subtype") != "success":
            detail = str(envelope.get("result") or envelope)[:500]
            if _is_usage_limit(detail):
                raise LLMUsageLimitError(detail)
            raise RuntimeError(f"claude CLI returned an error envelope: {detail}")

        # The CLI reports the real API-equivalent cost (what you're NOT paying in credits) + session.
        logger.info(
            "LLM via Claude Code CLI (subscription plan): model=%s notional_cost_usd=%s tier=%s session=%s",
            model, envelope.get("total_cost_usd"), _tier_of(model), envelope.get("session_id"),
        )
        return envelope.get("result", "")
