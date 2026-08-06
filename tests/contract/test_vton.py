"""T014 — legacy VTON contract tests (FR-012, Constitution I).

The AI provider (google-genai) and outbound httpx calls are mocked; these
tests assert request/response *shapes* for the five legacy endpoints and
`ENABLE_AUTH` gating behavior, not real model output.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_openai_reply(reply_text: str = "Hello from the AI consultant"):
    return reply_text


class TestConsultContract:
    def test_requires_message(self, client):
        response = client.post("/consult", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_rejects_empty_message(self, client):
        response = client.post("/consult", json={"message": ""})
        assert response.status_code == 422

    def test_success_shape(self, client):
        with patch("app.services.ai_text.generate_chat_reply", return_value=_fake_openai_reply("Try a linen palette for your venue.")):
            response = client.post("/consult", json={"message": "What should I wear?"})
        assert response.status_code == 200
        body = response.json()
        assert "reply" in body
        assert body["reply"] == "Try a linen palette for your venue."

    def test_open_mode_allows_anonymous(self, client, settings_override):
        with settings_override({"ENABLE_AUTH": "false"}):
            with patch("app.services.ai_text.generate_chat_reply", return_value=_fake_openai_reply()):
                response = client.post("/consult", json={"message": "hi"})
        assert response.status_code == 200

    def test_gated_mode_rejects_anonymous(self, client, settings_override):
        with settings_override({"ENABLE_AUTH": "true"}):
            response = client.post("/consult", json={"message": "hi"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    def test_gated_mode_allows_valid_token(self, client, settings_override, user_token):
        with settings_override({"ENABLE_AUTH": "true"}):
            with patch("app.services.ai_text.generate_chat_reply", return_value=_fake_openai_reply()):
                response = client.post(
                    "/consult",
                    json={"message": "hi"},
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200

    def test_upstream_failure_is_sanitized(self, client):
        with patch("app.services.ai_text.generate_chat_reply", side_effect=RuntimeError("some internal upstream text")):
            response = client.post("/consult", json={"message": "hi"})
        assert response.status_code == 503
        assert "some internal upstream text" not in response.text


class TestTestTryOnContract:
    def test_requires_body_image(self, client):
        response = client.post(
            "/test-try-on",
            json={"garment_image": "https://example.com/g.png", "category": "dress"},
        )
        assert response.status_code == 422

    def test_rejects_non_http_url(self, client):
        response = client.post(
            "/test-try-on",
            json={
                "body_image": "not-a-url",
                "garment_image": "https://example.com/g.png",
                "category": "dress",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_rejects_private_ip_ssrf(self, client):
        response = client.post(
            "/test-try-on",
            json={
                "body_image": "http://127.0.0.1/secret",
                "garment_image": "https://example.com/g.png",
                "category": "dress",
            },
        )
        assert response.status_code in (400, 422, 503)

    def test_open_mode_allows_anonymous_validation_error(self, client, settings_override):
        """Even in open mode, malformed input still 422s (auth != validation)."""
        with settings_override({"ENABLE_AUTH": "false"}):
            response = client.post("/test-try-on", json={})
        assert response.status_code == 422

    def test_gated_mode_rejects_anonymous(self, client, settings_override):
        with settings_override({"ENABLE_AUTH": "true"}):
            response = client.post(
                "/test-try-on",
                json={
                    "body_image": "https://example.com/b.png",
                    "garment_image": "https://example.com/g.png",
                    "category": "dress",
                },
            )
        assert response.status_code == 401


class TestTestTryOnUploadContract:
    def test_missing_files_is_422(self, client):
        response = client.post("/test-try-on-upload", data={"category": "dress"})
        assert response.status_code == 422

    def test_empty_file_is_rejected(self, client):
        response = client.post(
            "/test-try-on-upload",
            data={"category": "dress"},
            files={
                "body_image": ("body.png", b"", "image/png"),
                "garment_image": ("garment.png", b"garment-bytes", "image/png"),
            },
        )
        assert response.status_code == 422

    def test_gated_mode_rejects_anonymous(self, client, settings_override):
        with settings_override({"ENABLE_AUTH": "true"}):
            response = client.post(
                "/test-try-on-upload",
                data={"category": "dress"},
                files={
                    "body_image": ("body.png", b"body-bytes", "image/png"),
                    "garment_image": ("garment.png", b"garment-bytes", "image/png"),
                },
            )
        assert response.status_code == 401


class TestProxyImageContract:
    def test_blocks_private_ip(self, client):
        response = client.get("/proxy-image", params={"url": "http://127.0.0.1/x.png"})
        assert response.status_code in (400, 403, 422)

    def test_blocks_link_local(self, client):
        response = client.get("/proxy-image", params={"url": "http://169.254.169.254/x.png"})
        assert response.status_code in (400, 403, 422)

    def test_requires_url_param(self, client):
        response = client.get("/proxy-image")
        assert response.status_code == 422

    def test_gated_mode_rejects_anonymous(self, client, settings_override):
        with settings_override({"ENABLE_AUTH": "true"}):
            response = client.get(
                "/proxy-image", params={"url": "https://example.com/x.png"}
            )
        assert response.status_code == 401


class TestLegacyHealthContract:
    def test_root_health_delegates_to_canonical_shape(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        for key in ("ok", "service", "model", "provider"):
            assert key in body
