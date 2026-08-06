"""Environment-driven settings (Constitution III: all configuration from env).

No secret, project ID, or model name is committed here — every value is read
from the environment, with only non-sensitive local-development defaults.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- HTTP server (Constitution III: never hardcode the port) ---
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # --- CORS (Constitution IV: explicit allowlist, never "*") ---
    allowed_origins: str = "http://localhost:3000"

    # --- Auth gating.
    # Governs the pre-existing AI endpoints only. /api/v1/me/* and
    # /api/v1/admin/* always require a verified caller regardless of this flag
    # (plan.md Complexity Tracking, T008).
    enable_auth: bool = False

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_timeout_seconds: float = 8.0

    # --- Google / GenAI (existing AI endpoints, quickstart.md §2) ---
    google_genai_use_vertexai: bool = False
    google_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    google_text_model: str = "gemini-2.5-flash"
    nano_banana_model: str = ""

    # --- OpenAI-compatible provider (chat/consult text replies) ---
    # Any provider exposing an OpenAI-compatible /chat/completions API.
    ai_text_provider: str = "openai"
    openai_api_key: str = ""
    # Optional. Leave empty to use the default OpenAI endpoint; set to e.g.
    # https://api.deepseek.com/v1 or a local Ollama gateway to point elsewhere.
    openai_base_url: str = ""
    # Model name verbatim as the provider expects it (e.g. gpt-4o-mini,
    # deepseek-chat, llama3.1).
    ai_text_model: str = ""

    # --- Outbound image proxy limits (Constitution IV: SSRF/size caps) ---
    proxy_image_timeout_seconds: float = 10.0
    proxy_image_max_bytes: int = 10 * 1024 * 1024

    # --- Upload limits for the try-on endpoints ---
    upload_max_bytes: int = 10 * 1024 * 1024

    # --- Bounded page sizes (data-model.md invariant 8) ---
    default_page_size: int = Field(default=50, ge=1, le=200)
    max_page_size: int = Field(default=200, ge=1, le=1000)

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse the comma-separated allowlist.

        A literal "*" is rejected at the app layer rather than silently
        widening CORS (Constitution IV).
        """
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def supabase_rest_url(self) -> str:
        return f"{self.supabase_url}/rest/v1"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def vertex_configured(self) -> bool:
        return bool(self.google_genai_use_vertexai and self.google_cloud_project)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings.

    Cached for import cost only; the object is immutable configuration, not
    request state, so this does not violate Constitution III's statelessness
    requirement.
    """
    return Settings()
