"""Unit tests for ``app.services.ai_text``.

Covers the OpenAI-compatible provider path used by `/consult` and the chat
router: the client must be constructed with the configured `base_url`
(custom provider support, e.g. `OPENAI_BASE_URL=https://api.shopaikey.com/v1`)
and `api_key`, the configured model name must be forwarded verbatim, and the
first choice's message content must be returned trimmed.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings
from app.errors import UpstreamUnavailableError
from app.services import ai_text


def _fake_completion(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestOpenAIClientConstruction:
    def test_uses_custom_base_url_and_api_key(self, monkeypatch: pytest.MonkeyPatch):
        """A custom OpenAI-compatible provider (non-default base_url) must be
        passed through to the SDK client unchanged, matching backend/.env's
        OPENAI_BASE_URL=https://api.shopaikey.com/v1 configuration."""
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-custom-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.shopaikey.com/v1")
        monkeypatch.setenv("AI_TEXT_MODEL", "gpt-4o-mini")
        get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_completion("Xin chào!")

        with patch.object(ai_text, "OpenAI", return_value=mock_client) as mock_ctor:
            reply = ai_text.generate_chat_reply("Tìm giúp tôi váy cưới")

        mock_ctor.assert_called_once_with(
            api_key="sk-custom-key", base_url="https://api.shopaikey.com/v1"
        )
        mock_client.chat.completions.create.assert_called_once()
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == "gpt-4o-mini"
        # The consultant persona is now always injected as a system turn ahead
        # of the user message.
        assert kwargs["messages"][0]["role"] == "system"
        assert "Song Hỷ" in kwargs["messages"][0]["content"]
        assert kwargs["messages"][-1] == {
            "role": "user",
            "content": "Tìm giúp tôi váy cưới",
        }
        assert reply == "Xin chào!"

    def test_omits_base_url_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
        # Empty env value overrides any local .env value while preserving the
        # production behavior: ai_text.py omits base_url when it is blank.
        monkeypatch.setenv("OPENAI_BASE_URL", "")
        get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_completion("ok")

        with patch.object(ai_text, "OpenAI", return_value=mock_client) as mock_ctor:
            ai_text.generate_chat_reply("hi")

        mock_ctor.assert_called_once_with(api_key="sk-default")

    def test_falls_back_to_google_text_model_when_ai_text_model_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
        # Empty env value overrides any local .env value so the fallback path
        # is tested deterministically.
        monkeypatch.setenv("AI_TEXT_MODEL", "")
        monkeypatch.setenv("GOOGLE_TEXT_MODEL", "gemini-2.5-flash")
        get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_completion("ok")

        with patch.object(ai_text, "OpenAI", return_value=mock_client):
            ai_text.generate_chat_reply("hi")

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == "gemini-2.5-flash"


class TestOpenAIReplyParsing:
    def test_strips_reply_whitespace(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
        get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_completion(
            "  Đây là câu trả lời.  \n"
        )

        with patch.object(ai_text, "OpenAI", return_value=mock_client):
            reply = ai_text.generate_chat_reply("hi")

        assert reply == "Đây là câu trả lời."

    def test_empty_choices_returns_empty_string(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
        get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = SimpleNamespace(choices=[])

        with patch.object(ai_text, "OpenAI", return_value=mock_client):
            reply = ai_text.generate_chat_reply("hi")

        assert reply == ""

    def test_upstream_error_is_wrapped(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
        get_settings.cache_clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("upstream secret detail")

        with patch.object(ai_text, "OpenAI", return_value=mock_client):
            with pytest.raises(UpstreamUnavailableError) as exc_info:
                ai_text.generate_chat_reply("hi")

        assert "upstream secret detail" not in str(exc_info.value)

    def test_missing_openai_package_raises_upstream_error(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("AI_TEXT_PROVIDER", "openai")
        get_settings.cache_clear()

        with patch.object(ai_text, "OpenAI", None):
            with pytest.raises(UpstreamUnavailableError):
                ai_text.generate_chat_reply("hi")
