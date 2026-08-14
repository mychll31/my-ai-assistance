"""_call_llm must route to whichever provider key is present — including Groq."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_parser

PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "GROQ_MODEL")


def only_env(**overrides):
    """Environment with every provider key cleared except the given overrides."""
    env = {k: v for k, v in os.environ.items() if k not in PROVIDER_KEYS}
    env.update(overrides)
    return mock.patch.dict(os.environ, env, clear=True)


def fake_openai(content='{"type":"unknown"}'):
    client = mock.MagicMock()
    client.chat.completions.create.return_value.choices = [
        mock.MagicMock(message=mock.MagicMock(content=content))
    ]
    return mock.patch("openai.OpenAI", return_value=client), client


def test_groq_key_alone_is_enough():
    """The bug: a Groq-only setup transcribed fine but could not parse."""
    patch_openai, client = fake_openai()
    with only_env(GROQ_API_KEY="gsk_test"), patch_openai:
        assert ai_parser._call_llm("hello") == '{"type":"unknown"}'

    assert client.chat.completions.create.called


def test_groq_uses_groq_base_url_and_key():
    patch_openai, _ = fake_openai()
    with only_env(GROQ_API_KEY="gsk_test"), patch_openai as ctor:
        ai_parser._call_llm("hello")

    kwargs = ctor.call_args.kwargs
    assert kwargs["base_url"] == "https://api.groq.com/openai/v1"
    assert kwargs["api_key"] == "gsk_test"


def test_groq_model_is_overridable():
    """Groq retires model IDs; GROQ_MODEL must avoid needing a redeploy of code."""
    patch_openai, client = fake_openai()
    with only_env(GROQ_API_KEY="gsk_test", GROQ_MODEL="custom-model"), patch_openai:
        ai_parser._call_llm("hello")

    assert client.chat.completions.create.call_args.kwargs["model"] == "custom-model"


def test_openai_still_takes_precedence_over_groq():
    patch_openai, client = fake_openai()
    with only_env(OPENAI_API_KEY="sk_test", GROQ_API_KEY="gsk_test"), patch_openai as ctor:
        ai_parser._call_llm("hello")

    # OpenAI branch builds the client with no base_url override.
    assert "base_url" not in ctor.call_args.kwargs
    assert client.chat.completions.create.call_args.kwargs["model"] == "gpt-4o-mini"


def test_no_key_still_raises():
    with only_env():
        try:
            ai_parser._call_llm("hello")
        except RuntimeError as e:
            assert "GROQ_API_KEY" in str(e), "error should name every accepted key"
        else:
            raise AssertionError("expected RuntimeError when no provider key is set")
