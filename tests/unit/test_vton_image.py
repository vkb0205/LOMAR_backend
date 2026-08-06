"""Unit tests for the VTON image path (`app.routers.vton._run_image_model`).

Complements `tests/contract/test_vton.py`, which only reaches the validation
layer and never exercises the provider call. These tests cover the regression
that produced a 500 in production: the router called Google GenAI directly and
constructed the client outside any error handling, so an unconfigured
`GOOGLE_API_KEY` raised a bare `ValueError` that escaped to the catch-all
handler. The path now routes through `app.services.ai_image` (shopaikey), which
is what this deployment is actually configured for.

`generate_image` and Supabase Storage are stubbed — no network, no bucket
(Constitution VI: CI stays offline).
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest

from app.errors import UpstreamUnavailableError
# Aliased on import: pytest tries to collect any module-level name starting with
# "Test" as a test class, and warns because the Pydantic model has __init__.
from app.routers.vton import TestTryOnResponse as TryOnResponse
from app.routers.vton import _run_image_model


class _FakeBucket:
    def __init__(self, log: list, fail: bool = False) -> None:
        self._log = log
        self._fail = fail

    async def upload(self, path: str, data: bytes, opts: dict):
        if self._fail:
            raise RuntimeError("storage down")
        self._log.append((path, len(data), opts.get("contentType")))
        return {"path": path}

    def get_public_url(self, path: str) -> str:
        return f"https://cdn.test/{path}"


class _FakeStorage:
    def __init__(self, log: list, fail: bool = False) -> None:
        self._log = log
        self._fail = fail

    def from_(self, bucket: str) -> _FakeBucket:
        assert bucket == "generated"
        return _FakeBucket(self._log, self._fail)


class _FakeSupabase:
    def __init__(self, log: list | None = None, fail: bool = False) -> None:
        self.storage = _FakeStorage(log if log is not None else [], fail)


def _stub(url: str | None = "https://cdn.test/out.png", b64: str | None = None):
    """Return (patcher, captured) for a stubbed provider call."""
    captured: dict = {}

    async def _fake(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return {"url": url, "b64_json": b64, "model": "nano-banana-2"}

    return patch("app.services.ai_image.generate_image", _fake), captured


class TestUploadPath:
    """Multipart path: raw bytes must become URLs before the provider is called."""

    @pytest.mark.asyncio
    async def test_bytes_are_uploaded_and_passed_as_reference_urls(self):
        uploads: list = []
        patcher, captured = _stub()

        with patcher:
            result = await _run_image_model(
                supabase=_FakeSupabase(uploads),
                body_image_url="",
                garment_image_url="",
                category="dress",
                prompt="thêm dây chuyền",
                body_bytes=b"body-bytes",
                garment_bytes=b"garment-bytes",
            )

        # Both blobs stored, both handed to the provider as fetchable URLs:
        # shopaikey only accepts references as URLs (guide_img_api.md).
        assert len(uploads) == 2
        assert len(captured["reference_urls"]) == 2
        assert all(u.startswith("https://") for u in captured["reference_urls"])
        assert result.image_url == "https://cdn.test/out.png"

    @pytest.mark.asyncio
    async def test_body_reference_precedes_garment(self):
        """Order is semantic: the prompt refers to "first"/"second" image."""
        uploads: list = []
        patcher, captured = _stub()
        with patcher:
            await _run_image_model(
                supabase=_FakeSupabase(uploads),
                body_image_url="",
                garment_image_url="",
                category="dress",
                prompt="",
                body_bytes=b"AAA",
                garment_bytes=b"BB",
            )
        # Sizes disambiguate which upload came first.
        assert [size for _, size, _ in uploads] == [3, 2]

    @pytest.mark.asyncio
    async def test_user_prompt_is_included(self):
        patcher, captured = _stub()
        with patcher:
            await _run_image_model(
                supabase=_FakeSupabase(),
                body_image_url="",
                garment_image_url="",
                category="dress",
                prompt="thêm dây chuyền vào váy cưới này",
                body_bytes=b"a",
                garment_bytes=b"b",
            )
        assert "thêm dây chuyền vào váy cưới này" in captured["prompt"]
        assert "dress" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_missing_storage_raises_503_not_500(self):
        """The original defect: this must not escape as an unhandled error."""
        patcher, _ = _stub()
        with patcher:
            with pytest.raises(UpstreamUnavailableError) as exc:
                await _run_image_model(
                    supabase=None,
                    body_image_url="",
                    garment_image_url="",
                    category="dress",
                    prompt="",
                    body_bytes=b"a",
                    garment_bytes=b"b",
                )
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_storage_failure_raises_503(self):
        """A failed reference upload is fatal: the provider could not see it."""
        patcher, _ = _stub()
        with patcher:
            with pytest.raises(UpstreamUnavailableError):
                await _run_image_model(
                    supabase=_FakeSupabase(fail=True),
                    body_image_url="",
                    garment_image_url="",
                    category="dress",
                    prompt="",
                    body_bytes=b"a",
                    garment_bytes=b"b",
                )


class TestUrlPath:
    """JSON path: URLs are already fetchable and need no storage round-trip."""

    @pytest.mark.asyncio
    async def test_urls_passed_through_without_upload(self):
        uploads: list = []
        patcher, captured = _stub()
        with patcher:
            result = await _run_image_model(
                supabase=_FakeSupabase(uploads),
                body_image_url="https://example.com/body.png",
                garment_image_url="https://example.com/garment.png",
                category="dress",
                prompt="",
            )
        assert uploads == []  # nothing written to storage
        assert captured["reference_urls"] == [
            "https://example.com/body.png",
            "https://example.com/garment.png",
        ]
        assert result.image_url


class TestResponseShape:
    """Constitution I: the frontend reads `imageUrl` off this response."""

    @pytest.mark.asyncio
    async def test_image_url_survives_alias_serialization(self):
        """Regression: the alias silently dropped values built by field name.

        `image_url` carries `alias="imageUrl"`, so without `populate_by_name`
        the constructor discarded the value and emitted `imageUrl: null` —
        which the frontend surfaces as "response did not include an image URL".
        """
        patcher, _ = _stub(url="https://cdn.test/final.png")
        with patcher:
            result = await _run_image_model(
                supabase=_FakeSupabase(),
                body_image_url="https://example.com/b.png",
                garment_image_url="https://example.com/g.png",
                category="dress",
                prompt="",
            )
        assert result.image_url == "https://cdn.test/final.png"
        assert result.model_dump(by_alias=True)["imageUrl"] == "https://cdn.test/final.png"

    def test_model_accepts_both_key_spellings(self):
        assert TryOnResponse(image_url="X").image_url == "X"
        assert TryOnResponse(imageUrl="X").image_url == "X"


class TestBase64Result:
    @pytest.mark.asyncio
    async def test_b64_response_is_persisted_to_storage(self):
        uploads: list = []
        payload = base64.b64encode(b"generated").decode()
        patcher, _ = _stub(url=None, b64=payload)
        with patcher:
            result = await _run_image_model(
                supabase=_FakeSupabase(uploads),
                body_image_url="https://example.com/b.png",
                garment_image_url="https://example.com/g.png",
                category="dress",
                prompt="",
            )
        assert len(uploads) == 1
        assert result.image_url.startswith("https://cdn.test/outputs/")

    @pytest.mark.asyncio
    async def test_b64_falls_back_to_data_uri_without_storage(self):
        """A storage outage degrades sharability, not the request."""
        payload = base64.b64encode(b"generated").decode()
        patcher, _ = _stub(url=None, b64=payload)
        with patcher:
            result = await _run_image_model(
                supabase=None,
                body_image_url="https://example.com/b.png",
                garment_image_url="https://example.com/g.png",
                category="dress",
                prompt="",
            )
        assert result.image_url.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_empty_provider_result_raises_503(self):
        patcher, _ = _stub(url=None, b64=None)
        with patcher:
            with pytest.raises(UpstreamUnavailableError):
                await _run_image_model(
                    supabase=None,
                    body_image_url="https://example.com/b.png",
                    garment_image_url="https://example.com/g.png",
                    category="dress",
                    prompt="",
                )
