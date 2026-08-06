"""Unit tests for ``app.services.ai_image`` (Nano Banana image generation).

The provider is mocked at the ``httpx.AsyncClient`` boundary throughout — no
test performs a real request, so the suite costs nothing to run and does not
depend on the upstream being reachable.

Coverage focuses on the parts that are easy to get silently wrong: the
endpoint/auth wiring, the model-conditional ``imageSize`` parameter, the SSRF
screening of caller-supplied reference URLs, and the guarantee that upstream
error text never escapes into a client-visible message.
"""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.config import get_settings
from app.errors import UpstreamUnavailableError, ValidationError
from app.services import ai_image


@pytest.fixture(autouse=True)
def _configured_env(monkeypatch: pytest.MonkeyPatch):
    """Baseline: image generation configured and enabled."""
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://api.shopaikey.com")
    monkeypatch.setenv("IMAGE_API_KEY", "sk-image-key")
    monkeypatch.setenv("IMAGE_MODEL", "nano-banana-2")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mock_response(
    status_code: int = 200,
    json_body: Any | None = None,
    *,
    text: str = "",
) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    if json_body is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_body
    return response


def _patch_post(response: MagicMock) -> Any:
    """Patch httpx.AsyncClient so .post returns *response*."""
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch.object(ai_image.httpx, "AsyncClient", return_value=client), client


_OK_URL_BODY = {"created": 1, "data": [{"url": "https://cdn.example.com/a.png"}]}


class TestRequestWiring:
    @pytest.mark.asyncio
    async def test_posts_to_generations_endpoint_with_bearer_auth(self):
        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            result = await ai_image.generate_image("a red dress")

        client.post.assert_awaited_once()
        args, kwargs = client.post.call_args
        assert args[0] == "https://api.shopaikey.com/images/google/generations"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-image-key"
        assert result["url"] == "https://cdn.example.com/a.png"
        assert result["b64_json"] is None

    @pytest.mark.asyncio
    async def test_base_url_trailing_slash_does_not_double_up(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("IMAGE_API_BASE_URL", "https://api.shopaikey.com/")
        get_settings.cache_clear()

        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            await ai_image.generate_image("x")

        assert (
            client.post.call_args[0][0]
            == "https://api.shopaikey.com/images/google/generations"
        )

    @pytest.mark.asyncio
    async def test_image_key_falls_back_to_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """One shopaikey credential serves both surfaces."""
        monkeypatch.setenv("IMAGE_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-shared")
        get_settings.cache_clear()

        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            await ai_image.generate_image("x")

        assert client.post.call_args[1]["headers"]["Authorization"] == "Bearer sk-shared"


class TestPayload:
    @pytest.mark.asyncio
    async def test_includes_image_size_for_supporting_models(self):
        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            await ai_image.generate_image(
                "x", model="nano-banana-pro", size="16:9", image_size="4K"
            )

        payload = client.post.call_args[1]["json"]
        assert payload["model"] == "nano-banana-pro"
        assert payload["size"] == "16:9"
        assert payload["imageSize"] == "4K"

    @pytest.mark.asyncio
    async def test_omits_image_size_for_base_nano_banana(self):
        """nano-banana has a fixed output size and rejects imageSize."""
        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            await ai_image.generate_image("x", model="nano-banana")

        assert "imageSize" not in client.post.call_args[1]["json"]

    @pytest.mark.asyncio
    async def test_omits_image_urls_when_no_references(self):
        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            await ai_image.generate_image("x")

        assert "image_urls" not in client.post.call_args[1]["json"]


class TestValidation:
    @pytest.mark.asyncio
    async def test_rejects_empty_prompt(self):
        with pytest.raises(ValidationError):
            await ai_image.generate_image("   ")

    @pytest.mark.asyncio
    async def test_rejects_unknown_aspect_ratio(self):
        with pytest.raises(ValidationError) as exc:
            await ai_image.generate_image("x", size="7:3")
        assert "size" in exc.value.extra["fields"]

    @pytest.mark.asyncio
    async def test_rejects_unknown_image_size(self):
        with pytest.raises(ValidationError):
            await ai_image.generate_image("x", image_size="8K")

    @pytest.mark.asyncio
    async def test_rejects_unknown_format(self):
        with pytest.raises(ValidationError):
            await ai_image.generate_image("x", fmt="webp")

    @pytest.mark.asyncio
    async def test_rejects_oversized_prompt(self):
        with pytest.raises(ValidationError):
            await ai_image.generate_image("a" * 5000)

    @pytest.mark.asyncio
    async def test_validation_happens_before_any_network_call(self):
        """Bad input must not spend an upstream request."""
        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            with pytest.raises(ValidationError):
                await ai_image.generate_image("x", size="nope")
        client.post.assert_not_awaited()


class TestReferenceUrls:
    @pytest.mark.asyncio
    async def test_accepts_valid_https_references(self):
        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            await ai_image.generate_image(
                "x", reference_urls=["https://example.com/a.jpg"]
            )

        assert client.post.call_args[1]["json"]["image_urls"] == [
            "https://example.com/a.jpg"
        ]

    @pytest.mark.asyncio
    async def test_blocks_private_address_reference(self):
        """The provider fetches these server-side: SSRF by proxy."""
        with pytest.raises(ValidationError) as exc:
            await ai_image.generate_image(
                "x", reference_urls=["http://169.254.169.254/latest/meta-data/"]
            )
        assert "blocked" in exc.value.message.lower()

    @pytest.mark.asyncio
    async def test_blocks_loopback_reference(self):
        with pytest.raises(ValidationError):
            await ai_image.generate_image("x", reference_urls=["http://127.0.0.1/x.png"])

    @pytest.mark.asyncio
    async def test_rejects_non_http_scheme(self):
        with pytest.raises(ValidationError):
            await ai_image.generate_image("x", reference_urls=["file:///etc/passwd"])

    @pytest.mark.asyncio
    async def test_enforces_reference_count_limit(self):
        with pytest.raises(ValidationError) as exc:
            await ai_image.generate_image(
                "x",
                model="nano-banana",
                reference_urls=[f"https://example.com/{i}.jpg" for i in range(4)],
            )
        assert "image_urls" in exc.value.extra["fields"]


class TestFailureHandling:
    @pytest.mark.asyncio
    async def test_unconfigured_raises_without_calling_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("IMAGE_API_BASE_URL", "")
        get_settings.cache_clear()

        patcher, client = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            with pytest.raises(UpstreamUnavailableError):
                await ai_image.generate_image("x")
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upstream_error_text_is_not_leaked_to_client(self):
        """Constitution IV: provider detail stays in logs, not the envelope."""
        secret = "invalid api key sk-5EAiA6CNDAmXwyewsIMXf4rs at 10.0.0.7"
        patcher, _ = _patch_post(
            _mock_response(401, {"error": {"message": secret}})
        )
        with patcher:
            with pytest.raises(UpstreamUnavailableError) as exc:
                await ai_image.generate_image("x")

        assert secret not in exc.value.message
        assert "sk-5EAiA6" not in exc.value.message
        assert "10.0.0.7" not in exc.value.message

    @pytest.mark.asyncio
    async def test_transport_failure_becomes_upstream_unavailable(self):
        client = MagicMock()
        client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(ai_image.httpx, "AsyncClient", return_value=client):
            with pytest.raises(UpstreamUnavailableError):
                await ai_image.generate_image("x")

    @pytest.mark.asyncio
    async def test_unreadable_json_becomes_upstream_unavailable(self):
        patcher, _ = _patch_post(_mock_response(200, None, text="<html>502</html>"))
        with patcher:
            with pytest.raises(UpstreamUnavailableError):
                await ai_image.generate_image("x")

    @pytest.mark.asyncio
    async def test_empty_data_array_is_an_error_not_an_empty_success(self):
        patcher, _ = _patch_post(_mock_response(200, {"created": 1, "data": []}))
        with patcher:
            with pytest.raises(UpstreamUnavailableError):
                await ai_image.generate_image("x")


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_returns_b64_when_provider_sends_base64(self):
        patcher, _ = _patch_post(
            _mock_response(200, {"created": 1, "data": [{"b64_json": "iVBORw0KGgo="}]})
        )
        with patcher:
            result = await ai_image.generate_image("x", response_format="b64_json")

        assert result["b64_json"] == "iVBORw0KGgo="
        assert result["url"] is None

    @pytest.mark.asyncio
    async def test_reports_the_model_actually_used(self):
        patcher, _ = _patch_post(_mock_response(200, _OK_URL_BODY))
        with patcher:
            result = await ai_image.generate_image("x", model="nano-banana-pro")

        assert result["model"] == "nano-banana-pro"
